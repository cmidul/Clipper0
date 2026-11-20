import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, realpathSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

const WebSocket = createRequire(import.meta.url)("next/dist/compiled/ws");
const dashboard = "http://127.0.0.1:3000/";
const frameUrl = "http://127.0.0.1:8000/test-export-frame.svg";
const edge = process.argv[2] ?? "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const profilePrefix = "clipper0-export-test-";
const tempRoot = realpathSync(tmpdir());
const profile = mkdtempSync(join(tempRoot, profilePrefix));
const browser = spawn(edge, [
  "--headless", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-sync",
  "--no-first-run", "--no-default-browser-check", "--no-proxy-server",
  "--enable-logging=stderr",
  "--host-resolver-rules=EXCLUDE 127.0.0.1, EXCLUDE localhost, MAP * ~NOTFOUND", "--remote-debugging-port=0",
  "--user-data-dir=" + profile, "about:blank",
], { stdio: ["ignore", "ignore", "pipe"], windowsHide: true });
const closed = new Promise((resolve) => browser.once("close", () => resolve(true)));
let launchError;
browser.on("error", (error) => { launchError = error; });
let diagnostics = "";
browser.stderr.setEncoding("utf8");
browser.stderr.on("data", (chunk) => { diagnostics = (diagnostics + chunk).slice(-4000); });

async function waitFor(check, description) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (launchError) throw launchError;
    const result = await check();
    if (result) return result;
    await delay(100);
  }
  throw new Error("Timed out waiting for " + description);
}

function installProjectFixture() {
  const media = {
    id: "a".repeat(32), filename: "Export settings fixture.mp4", duration: 30, width: 640, height: 360,
    size_bytes: 1024, asset_status: "available", archived_at: null,
  };
  const job = {
    id: "b".repeat(32), media_id: media.id, state: "completed", phase: "done", kind: "render",
    created_at: "2026-01-01T00:00:00Z", elapsed_seconds: 1,
    options: { layout: "pad", aspect_ratio: "4:5", resolution: 480, compression: "smaller_file", framing: { mode: "full_gameplay" } },
  };
  const fetchOriginal = window.fetch.bind(window);
  window.exportSettingsTestRequestCount = 0;
  window.fetch = (input, options) => {
    const url = new URL(input instanceof Request ? input.url : input, location.href);
    if (url.origin !== "http://127.0.0.1:8000") return fetchOriginal(input, options);
    window.exportSettingsTestRequestCount += 1;
    const archived = url.searchParams.get("archived") === "true";
    let data;
    if (url.pathname === "/media") data = archived ? [] : [media];
    else if (url.pathname === "/jobs") data = archived ? [] : [job];
    else if (url.pathname === "/health") data = { status: "ok" };
    else if (url.pathname === "/jobs/" + job.id + "/candidates") data = [];
    else if (url.pathname === "/media/" + media.id + "/frames" && options?.method === "POST") {
      data = { state: "completed", frame_url: "/test-export-frame.svg" };
    } else {
      return Promise.reject(new Error("Unexpected browser fixture request " + url.pathname));
    }
    return Promise.resolve(Response.json(data));
  };
}

let socket;
try {
  const port = await waitFor(() => {
    try {
      return readFileSync(join(profile, "DevToolsActivePort"), "utf8").split(/\r?\n/)[0];
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
      return null;
    }
  }, "the isolated Edge debugging port");
  assert.match(port, /^\d+$/);
  const targets = await (await fetch("http://127.0.0.1:" + port + "/json/list", {
    signal: AbortSignal.timeout(5000),
  })).json();
  const target = targets.find((item) => item.type === "page");
  assert.ok(target, "Expected a headless browser tab");
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });

  let nextId = 0;
  const pending = new Map();
  function send(method, params = {}) {
    const id = ++nextId;
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        pending.delete(id);
        reject(new Error("Browser command timed out: " + method));
      }, 12000);
      pending.set(id, { resolve, reject, timeout });
      socket.send(JSON.stringify({ id, method, params }));
    });
  }
  let frameError;
  socket.addEventListener("message", ({ data }) => {
    const message = JSON.parse(data);
    if (message.method === "Fetch.requestPaused") {
      const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="steelblue"/></svg>';
      void send("Fetch.fulfillRequest", {
        requestId: message.params.requestId, responseCode: 200,
        responseHeaders: [{ name: "Content-Type", value: "image/svg+xml" }],
        body: Buffer.from(svg).toString("base64"),
      }).catch((error) => { frameError = error; });
    }
    const command = pending.get(message.id);
    if (!command) return;
    pending.delete(message.id);
    clearTimeout(command.timeout);
    if (message.error) command.reject(new Error(message.error.message));
    else command.resolve(message.result);
  });

  async function evaluate(callback, ...args) {
    const expression = "(" + callback.toString() + ")(..." + JSON.stringify(args) + ")";
    const result = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error(result.result.description ?? result.exceptionDetails.text);
    return result.result.value;
  }

  await send("Browser.getVersion");
  await send("Page.enable");
  await send("Page.addScriptToEvaluateOnNewDocument", { source: "(" + installProjectFixture.toString() + ")()" });
  await send("Fetch.enable", { patterns: [{ urlPattern: frameUrl }] });
  const navigation = await send("Page.navigate", { url: dashboard });
  assert.ok(!navigation.errorText, navigation.errorText);
  try {
    await waitFor(() => evaluate(() => Boolean(document.querySelector(".job-row"))), "the restored job");
  } catch (error) {
    console.error("Dashboard startup:", await evaluate(() => ({
      atDashboard: location.origin === "http://127.0.0.1:3000",
      readyState: document.readyState,
      settingsForm: Boolean(document.querySelector(".settings-form")),
      fixtureRequests: window.exportSettingsTestRequestCount ?? null,
    })));
    throw error;
  }

  const controls = await evaluate(() => {
    const form = document.querySelector(".settings-form");
    return Array.from(form.querySelectorAll("label")).slice(0, 3).map((label) => ({
      name: label.firstChild.textContent.trim(), value: label.querySelector("select").value,
      options: Array.from(label.querySelector("select").options, (option) => option.text),
    }));
  });
  assert.deepEqual(controls, [
    { name: "Aspect Ratio", value: "4:5", options: ["9:16 (Vertical)", "16:9 (Horizontal)", "1:1 (Square)", "4:5 (Portrait)"] },
    { name: "Video Quality", value: "480", options: ["1080p — Full HD", "720p — HD", "480p — SD"] },
    { name: "Compression", value: "smaller_file", options: ["Higher Quality", "Balanced", "Smaller File"] },
  ]);
  assert.ok(await evaluate(() => document.querySelector(".settings-form").textContent.includes("A larger export cannot recover source detail.")));

  await evaluate(() => {
    const details = [...document.querySelectorAll(".settings-form .framing-editor details")].find(
      (element) => element.querySelector("summary").textContent === "Source preview and manual focus",
    );
    details.parentElement.closest("details").open = true;
    details.querySelector("summary").click();
    [...details.querySelectorAll("button")].find((button) => button.textContent === "Load source frame").click();
  });
  await waitFor(() => {
    if (frameError) throw frameError;
    return evaluate(() => document.querySelector(".source-frame img")?.naturalWidth === 640);
  }, "the synthetic source preview");
  const expected = {
    "9:16": [[480, 854], [720, 1280], [1080, 1920]],
    "16:9": [[854, 480], [1280, 720], [1920, 1080]],
    "1:1": [[480, 480], [720, 720], [1080, 1080]],
    "4:5": [[480, 600], [720, 900], [1080, 1350]],
  };
  for (const [ratio, sizes] of Object.entries(expected)) {
    for (const [index, resolution] of [480, 720, 1080].entries()) {
      const [width, height] = sizes[index];
      const actual = await evaluate(async (ratio, resolution) => {
        const form = document.querySelector(".settings-form");
        for (const [index, value] of [ratio, resolution].entries()) {
          const select = form.querySelectorAll("select")[index];
          select.value = String(value);
          select.dispatchEvent(new Event("change", { bubbles: true }));
          await new Promise((resolve) => setTimeout(resolve, 15));
        }
        return {
          readout: form.querySelector("[aria-live=polite]").textContent,
          preview: form.querySelector(".framing-output").style.aspectRatio,
        };
      }, ratio, resolution);
      assert.ok(actual.readout.includes("Output dimensions " + width + " × " + height + " px"));
      assert.equal(actual.preview, width + " / " + height);
    }
  }
  await evaluate(() => {
    const compression = document.querySelectorAll(".settings-form select")[2];
    compression.value = "higher_quality";
    compression.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await evaluate(() => {
    document.querySelector(".history-panel > summary").click();
    document.querySelector(".job-row").click();
  });
  await waitFor(() => evaluate(() => {
    const fields = [...document.querySelectorAll(".settings-form select")].slice(0, 3);
    return fields.map((field) => field.value).join(" ") === "4:5 480 smaller_file";
  }), "the reopened job's export settings");
  console.log("Browser verified the three selectors, 12 dimension readouts and preview canvases, and saved settings restoration.");
} catch (error) {
  if (diagnostics.trim()) console.error(diagnostics.trim());
  throw error;
} finally {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ id: -1, method: "Browser.close" }));
    socket.close();
  }
  if (!await Promise.race([closed, delay(5000, false)])) {
    browser.kill();
    await closed;
  }
  const resolvedProfile = realpathSync(profile);
  assert.equal(dirname(resolvedProfile), tempRoot);
  assert.ok(basename(resolvedProfile).startsWith(profilePrefix));
  rmSync(resolvedProfile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}
