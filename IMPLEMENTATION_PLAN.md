# Implementation Plan (Approval-Gated)

## Operating rule
Before every file edit, command, installation, test, or Git action: propose **one** action using `AGENTS.md`, wait for a clear Yes, perform exactly that action, report results, ask again. Milestones are NOT blanket approval.

## M0 — Laptop discovery and reproducible specification
- Ask: laptop OS/version, CPU, RAM, available SSD/HDD, disk drives, admin rights, recording resolution, expected language, and installed versions of Python, Node, FFmpeg, Git, OBS.
- Propose individual read-only validation commands; require approval for each.
- Select local paths and model parameters from measurements, not desktop assumptions.
- Record setup requirements and known constraints.
**Acceptance:** full laptop hardware/environment matrix; supported tool versions confirmed.

## M1 — Minimal useful clipping engine (no AI yet)
- Python package skeleton, config loader, health/preflight checks.
- FFprobe inspection; safe paths; import and validated media metadata.
- Audio envelope extraction, peak selection, candidate time-window normalization.
- FFmpeg landscape-to-vertical rendering (crop or pad), MP4 H.264/AAC; optional silence handling.
- CLI proof of concept: input recording -> 3 candidate clips + JSON manifest.
- Unit tests for timestamp clipping and selection; smoke-test a short user-owned video.
**Acceptance:** playable outputs, no bounds errors, import/render robust with paths containing spaces.

## M2 — Speech and subtitle pipeline
- CPU Faster-Whisper `base` INT8, chosen only after laptop capability check.
- Detect/no-speech handling, transcript JSON, segment SRT and rendered ASS captions.
- Verify subtitle timings, special characters, multilingual display/font fallback.
- Cache transcripts by media hash and model configuration.
**Acceptance:** video with speech generates readable captions; silent video does not fail.

## M3 — Better candidate ranking
- Audio features: RMS, activity change, optional spectral features.
- Transcript cue features (language-aware, carefully weighted); PySceneDetect optional.
- Transparent evidence vector, configurable weights, interval IoU NMS.
- Regression test set using known timestamps and edge cases; compare manual human picks.
**Acceptance:** top candidates are explainable; no duplicate or near-identical clips, no unsupported 'viral' claims.

## M4 — Local web interface and durable jobs
- Next.js TypeScript + Tailwind app (upload/import, job page, clips review).
- FastAPI localhost endpoints, safe media serving, SQLite schema/migrations, one-worker async queue.
- Progress, cancellation, error handling, rerender after timestamp changes.
- E2E smoke test on laptop.
**Acceptance:** 10-minute OBS recording -> up to 3 clips -> preview + download in browser; graceful errors.

## M5 — Improve usability and performance
- CPU/RAM profiling, progress feedback, caching, configurable model sizes and processing limits.
- Directory watch for completed OBS files (never read active/incomplete recordings); explicit opt-in.
- Basic feedback: approve/reject and reason, export manifest to improve rules.
**Acceptance:** 3 representative videos process reliably; timings and resource usage documented.

## M6 — GitHub transfer and desktop test
- Inspect `.gitignore` + privacy; user approval for every Git command and network action.
- Commit code/docs/config examples only, push to private GitHub repo if user approves.
- Clone to Windows 10 Ryzen 5 5600G desktop, install dependencies, set storage paths, locally download models.
- Repeat same acceptance tests, compare speed and memory. Make per-machine overrides in ignored `.env.local` and config.
**Acceptance:** no original videos/secrets in Git, clean clone builds, desktop reproduces MVP.

## Phase postponed until after MVP
True low-latency livestream segmenting, platform publishing APIs, multi-user hosted environment, GPU optimization, per-game event detectors.

## Smart reframing extension ? implemented source, acceptance in progress

Geometry/contracts ? composition ? engine/API/worker integration ? parent-transcript reuse ? sampled OpenCV analysis/cache and smooth tracking ? dashboard controls/queued previews ? automated and real-source comparison. See SMART_REFRAMING.md and progress.md for verification and remaining manual acceptance.
