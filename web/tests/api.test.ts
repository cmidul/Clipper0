import assert from "node:assert/strict";
import test from "node:test";
import { apiPath, apiRequest, ASPECT_RATIO_OPTIONS, COMPRESSION_OPTIONS, errorDetail, formatTime,
  intervalError, localApiBase, outputSizeLabel, processorErrorMessage, requestPreviewFrame, VIDEO_QUALITY_OPTIONS } from "../lib/api.ts";

test("shape, resolution, and compression have separate selector choices", () => {
  assert.deepEqual(ASPECT_RATIO_OPTIONS, [
    { value: "9:16", label: "9:16 (Vertical)" }, { value: "16:9", label: "16:9 (Horizontal)" },
    { value: "1:1", label: "1:1 (Square)" }, { value: "4:5", label: "4:5 (Portrait)" },
  ]);
  assert.deepEqual(VIDEO_QUALITY_OPTIONS, [
    { value: 1080, label: "1080p — Full HD" }, { value: 720, label: "720p — HD" }, { value: 480, label: "480p — SD" },
  ]);
  assert.deepEqual(COMPRESSION_OPTIONS.map(({ label }) => label), ["Higher Quality", "Balanced", "Smaller File"]);
});

test("output dimensions match the expected even canvas for all 12 selections", () => {
  const dimensions = [
    ["9:16", "480 × 854", "720 × 1280", "1080 × 1920"],
    ["16:9", "854 × 480", "1280 × 720", "1920 × 1080"],
    ["1:1", "480 × 480", "720 × 720", "1080 × 1080"],
    ["4:5", "480 × 600", "720 × 900", "1080 × 1350"],
  ] as const;
  for (const [ratio, sd, hd, fullHd] of dimensions) {
    assert.equal(outputSizeLabel(480, ratio), sd);
    assert.equal(outputSizeLabel(720, ratio), hd);
    assert.equal(outputSizeLabel(1080, ratio), fullHd);
  }
});

test("processor and asset URLs stay local", () => {
  assert.equal(localApiBase("http://127.0.0.1:8000"), "http://127.0.0.1:8000");
  for (const url of ["https://example.com", "http://example.com", "http://user:secret@localhost:8000", "http://localhost:8000/private"]) {
    assert.throws(() => localApiBase(url));
  }
  assert.throws(() => apiPath("//example.com/video"));
});

test("manual interval bounds reject invalid and out-of-source values", () => {
  assert.equal(intervalError(10, 30, 90), null);
  for (const [start, end, duration] of [[-1, 20, 90], [0, 14, 90], [0, 61, 90], [80, 100, 90], [NaN, 30, 90]]) {
    assert.ok(intervalError(start, end, duration));
  }
});

test("timestamps show hours for long recordings", () => {
  assert.equal(formatTime(65), "1:05");
  assert.equal(formatTime(3665.8), "1:01:05");
});

test("API validation and storage errors produce readable feedback", () => {
  assert.equal(errorDetail({ detail: "Missing executable" }, 503), "Missing executable");
  assert.equal(errorDetail({ detail: [{ msg: "Invalid interval" }] }, 422), "Invalid interval");
  assert.match(errorDetail(null, 500), /500/);
});

test("processor feedback keeps actionable errors and omits raw encoder and probe logs", () => {
  assert.equal(processorErrorMessage("Choose an MP4 or MKV recording."), "Choose an MP4 or MKV recording.");
  assert.equal(processorErrorMessage("ffmpeg.exe exceeded its 60s time limit."), "ffmpeg.exe exceeded its 60s time limit.");
  assert.equal(processorErrorMessage("ffmpeg.exe failed. [encoder] internal output"),
    "FFmpeg could not process this recording. Retry or try another recording.");
  assert.equal(errorDetail({ detail: "ffprobe failed. internal output" }, 422),
    "FFprobe could not read this recording. Check that the file plays and try importing it again.");
});

test("API client surfaces failures and preserves abort cancellation", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: "Disk unavailable" }), { status: 503 });
    await assert.rejects(apiRequest("/jobs"), /Disk unavailable/);
    globalThis.fetch = async () => { throw new TypeError("connection refused"); };
    await assert.rejects(apiRequest("/jobs"), /Cannot reach the local processor/);
    globalThis.fetch = async () => { throw new DOMException("Cancelled", "AbortError"); };
    await assert.rejects(apiRequest("/jobs"), { name: "AbortError" });
  } finally {
    globalThis.fetch = original;
  }
});

test("frame previews submit the requested parameters and poll the existing job route", async () => {
  const original = globalThis.fetch;
  const calls: { path: string; method?: string; body?: BodyInit | null }[] = [];
  const controller = new AbortController();
  try {
    globalThis.fetch = async (url, options) => {
      const path = new URL(String(url)).pathname;
      calls.push({ path, method: options?.method, body: options?.body });
      assert.equal(options?.signal, controller.signal);
      return Response.json(path === "/media/recording/frames"
        ? { id: "preview", state: "queued" }
        : { id: "preview", state: "completed", frame_url: "/frames/preview" });
    };
    assert.equal((await requestPreviewFrame("recording", { time: 5 }, controller.signal)).frame_url, "/frames/preview");
    assert.deepEqual(calls, [
      { path: "/media/recording/frames", method: "POST", body: '{"time":5}' },
      { path: "/jobs/preview", method: undefined, body: undefined },
    ]);
  } finally {
    globalThis.fetch = original;
  }
});
