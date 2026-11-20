# Clipper0 public beta release checklist

This checklist accompanies the [85/100 readiness report](RELEASE_READINESS.md). Any additional browser work, clean install, upstream research, project license, and publication need the applicable approval in [AGENTS.md](AGENTS.md).

## Gate 1 · Localhost browser acceptance

**Status** Passed following approval on 2026-11-20. The first automation attempt selected the file before the UI connected and timed out before upload. Waiting for the connection indicator fixed the test. Headless Edge completed upload, ranking, playback, seek, focus preview, revision, browser download, and reopening both jobs with the Focus Crop settings restored. FFprobe, full decode, and still/export comparison passed. The disposable source was unchanged and both test services were stopped.

- Use a fresh test folder under ignored `local-data/test-runs/`. Place the disposable MP4 outside the app-managed subdirectory. Use its own database, recordings directory, and model cache. Unset any inherited frontend API override in the test shell and set `NEXT_TELEMETRY_DISABLED=1`.
- Check that ports 3000 and 8000 are free. Run the current production build on `127.0.0.1:3000` with `npm.cmd run start` from `web/`. Start `python -m autoclip serve` with the workspace virtual environment, `AUTOCLIP_WORKER_THREADS=1`, and the isolated `AUTOCLIP_DATA_DIR`, `AUTOCLIP_DB_PATH`, `AUTOCLIP_RECORDINGS_DIR`, and `AUTOCLIP_MODEL_CACHE_DIR`.
- Open only `http://127.0.0.1:3000` in an isolated browser profile. Use the real API on port 8000. Keep all navigation and media transfer local. If a port is occupied, stop the check before launching either process.
- Use the generated 20-second 320×180 fixture with a gray frame, blue right-edge strip, and a one-second tone near second 8. The generator is recorded in `tests/test_backend_integration.py::test_ranked_clip_spatial_revision_matches_still_and_persists`.

| Step | Pass evidence |
| --- | --- |
| Upload | Select **Choose recording**, then the disposable MP4. Choose **Audio only**, one 15-second clip, 9:16, 480p, and **Full Frame** with a padded background. **Generate candidates** completes and shows one automatically selected result. A manual trim would diagnose rendering only. |
| Play | Click Play. The browser shows decoded video, advances playback time, and can seek. The full-frame result shows its padding and right-edge strip. |
| Adjust and preview | Open **Adjust clip**. Choose **Focus Crop**, turn off **Auto Focus**, move the horizontal focus right, and set 1.5× zoom. Open **Source preview and manual focus**. Use a timestamp within the candidate, load the source, and choose **Render preview frame**. The rendered still shows the enlarged blue strip. |
| Re-render | Select **Render revision**. Verify the new video plays with the changed crop, and the original job remains available. |
| Download | Use **Download** and confirm a finished file in the run's disposable download directory. FFprobe should show H.264/AAC, 480×854 square pixels, and approximately 15 seconds. Decode the file with FFmpeg. Compare the blue strip with the still and original. |
| Reopen | Reload the dashboard and reopen the recording from history. Verify both jobs are accessible, saved framing and 1.5× zoom are restored for the revision, and the revised video plays again. |
| Finish | Capture status and elapsed time for each step, relevant job/clip IDs, any exact failure text, and the download probe. Check fixture SHA-256 is unchanged. Stop only the processes created for the run. |

Use roughly 3–5 minutes, with the laptop awake. Do not apply browser points until the actual stages above have evidence.

## Gate 2 · Clean Windows installation

**Status** Pending dependency installation and end-to-end verification. The current machine's direct Python 3.14.7 x64 executable created a fresh temporary venv and bootstrapped pip without network access. Its shell aliases for `py.exe` and `python.exe` failed to launch in the managed session. The README includes the verified full-path fallback.

1. Create a disposable Windows 11 x64 copy of the exact reviewed source candidate outside the active project. Record the source commit and diff fingerprint. Begin with no `.venv`, `node_modules`, `.next`, `local-data`, or inherited `AUTOCLIP_*` paths.
2. Record versions of the installed Python interpreter, Node, npm, FFmpeg, and FFprobe. Check Python 3.14 x64, Node 24, and FFmpeg H.264, AAC, and libass capability. Use the README's explicit interpreter path if the launcher is unavailable.
3. Follow the README sequence exactly. Create the venv, install all three requirements files in one resolver run using binary wheels, run `pip check` and `autoclip health`, then run `npm.cmd ci` and the production build. Capture any resolver or wheel error and the resolved package versions. Compare the npm lockfile and Python manifests before and after the install.
4. Run `autoclip prepare-model` while online. Record the repository, revision, and cache location from `source.json`. The setup command resolves the upstream revision at download time, so record the actual revision checked.
5. For the offline leg, use a run environment with only loopback access. Start both services from the documented commands and confirm health. Run the disposable audio-only acceptance workflow. Run a separate short authorized speech fixture with the prepared model and confirm a captioned MP4 and SRT, with no fetch during inference.
6. Record the Windows version, package resolution, model revision, test outcomes, and the exact failed command if blocked. Claim Windows 10 support only after repeating the check there.

Prerequisite or package downloads, model preparation, and restricted networking policies require their own applicable approval. This plan uses temporary project state and does not change system network settings.

## Gate 3 · Dependency evidence and license choice

**Status** Local metadata checked. Upstream license and current advisory queries await approval.

- See [Third-party notices](THIRD_PARTY_NOTICES.md) for the locally installed licenses. Reconfirmed MIT, BSD, and Apache licenses across the main Python and web packages, SIL OFL-1.1 for Inter, and an installed GPL FFmpeg build obtained separately. The local Faster-Whisper provenance records MIT for `Systran/faster-whisper-base` at `ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66`. Verify the upstream card and notices at that exact revision and record the date and URL.
- After approval, query npm's advisory service for the lockfile, the OSV or GitHub Advisory databases for resolved PyPI versions and frontend pins, and FFmpeg's official security information for the tested version and build. Check transitive and runtime packages, including Next.js, React, Starlette, Uvicorn, PyAV, OpenCV, and the inference runtimes. Record advisory ID, affected and fixed versions, runtime exposure, mitigation or upgrade, and any lookup failures. Re-test any changed dependency. Offline or incomplete lookups leave this gate open.
- Keep the beta source-only. A later binary bundle would require the bundled upstream notices and a separate review of FFmpeg/x264, the font assets, and the model weights.

| Project license option | Tradeoff |
| --- | --- |
| MIT | Short permissive terms. Others can modify and redistribute the code with the copyright and license notice. |
| Apache-2.0 | Permissive reuse with an express contributor patent grant and patent-termination clause. Carries more notice obligations. |
| GPL-3.0-only | A copyleft option if the owner wants distributed derivative versions to retain GPL terms and corresponding source obligations. |

No project license has been selected. Add the canonical text only after the owner approves the license and confirms the copyright attribution. Retain the upstream notices separately.

## Gate 4 · Exact release diff and Git hygiene

Reviewed local base `0accf5bb43a253cf17b4c9110bb5d318df3a9fda`. Before staging, run the following read-only checks from the repository root.

```powershell
git rev-parse HEAD
git status --short
git diff --check HEAD
git diff --name-status HEAD
git diff --stat HEAD
git diff --no-ext-diff --no-textconv HEAD
git ls-files --others --exclude-standard
git ls-files --cached --ignored --exclude-standard
git check-ignore -v --no-index .env .env.local local-data/test.mp4 models/model.bin local-data/autoclip.sqlite3
```

- Review every changed file and explicitly include intended untracked docs. The working-tree diff omits untracked files. Review `CONTRIBUTING.md`, `RELEASE_READINESS.md`, `THIRD_PARTY_NOTICES.md`, and this checklist individually. Include the root `LICENSE` only after owner approval.
- Allow source, tests, docs, pinfiles, and environment examples. Check for recordings, MP4 outputs, subtitle/transcript content, model blobs, databases and sidecars, machine-specific paths, environments, credentials, and unexpected large files. Review the staged patch and messages for leaked identifiers. Ignore rules do not remove tracked files or history.
- When an exact candidate is staged, repeat `git diff --cached --check`, `git diff --cached --name-status HEAD`, and `git diff --cached --no-ext-diff --no-textconv HEAD`. Confirm the resulting committed SHA matches the browser/install evidence. Review `git show --format=fuller --stat <release-commit>` and `git diff --name-status <reviewed-base> <release-commit>`. Re-scan any additions after the recorded check.
- Verify the intended remote, branch, release label, and artifact list with the owner before any push, GitHub Release, visibility change, or announcement. Keep private recordings and generated downloads excluded.

**Local evidence** The index was clean, the working-tree diff passed its whitespace check, and representative ignored paths matched their rules. A scan of local reachable objects and candidate content found no sensitive media/weight/database paths or common secret patterns. This is a local pattern scan, with no claim about unobserved remote refs.
