# Changelog

## Unreleased — 2026-11-20

- Rebuilt the dashboard as a dark editing workspace with a Media Library, central Source and Output Monitor, Highlight Bin, compact job drawer, and contextual Inspector. Older projects and exports continue to use the existing routes and settings.

- Compacted the workspace, recording import, and empty states. Grouped clipping settings and moved advanced framing into a collapsible section.

- Simplified the framing dropdown to Focus Crop, Hybrid Focus, Full Frame, and Auto. Existing clips and saved legacy framing settings remain available.

- Added Focus Crop and Hybrid Focus, normalized focus and region editing, foreground zoom, and position locking. Composition stills and exports share the planner and FFmpeg graph.
- Fixed zoom for manually positioned Auto framing and bounded sampled analysis on both frame axes.
- Updated Windows setup, local demo steps, contribution guidance, and third-party notices for the beta audit. See the release-readiness report for verification and pending acceptance.

## Unreleased — 2026-11-19

- New recording opens an empty workspace. Choose recording opens the file picker. Pending job and preview responses cannot reopen the workspace the user left.
- Added project controls to archive recordings, restore them after restart, or confirm permanent deletion of their app-managed files. Cleanup protects original recordings and shared files, rejects active jobs, and reports per-file failures for retry. Project and job history remain available after cleanup.
- Added SQLite schema version 2 and regression tests for migration, archive and restore, job conflicts, and deletion safety. All 175 Python tests and 10 frontend tests passed, along with TypeScript, the production build, and localhost smoke checks. Interactive browser acceptance remains pending.

## Unreleased — 2026-11-18

- Added 9:16 portrait and 16:9 landscape choices to dashboard clip settings and timestamp revisions, with matching resolution labels and saved-ratio preview sizing.
- Added validated aspect_ratio API options and CLI --aspect-ratio. New and legacy jobs default to portrait; revisions retain their original ratio unless overridden. No database migration is required.
- Added landscape 1280×720 / 1920×1080 rendering alongside existing portrait sizes, with padding/cropping and matching caption canvas, font scaling, and margins.
- Added regression coverage for dimensions, invalid ratios, legacy jobs, revision inheritance/overrides, CLI options, subtitle geometry, and actual landscape FFmpeg rendering/decoding with captions at both resolutions and layouts. Added frontend resolution-label coverage and a reproducible manual checklist in README.
- Verification passed all 71 Python tests and 6 frontend tests with no skips, TypeScript checking, and the production build. Two additional live HTTP smoke tests verified both ratio choices in the delivered page, all 8 referenced assets, backend health, and the new API schema. Restarted both servers for manual testing. Interactive browser verification remains unavailable due to the browser tool's URL-confidence block.

## 0.4.0 — 2026-11-17

- Implemented the M4 backend chunk with FastAPI, a loopback-only `serve` command, and a durable single-worker SQLite queue.
- Added managed streamed uploads, copied local-folder imports, SHA-256/metadata validation, media/job listing and status, cancellation, candidate review, queued timestamp revisions, and safe MP4/SRT access with range-capable previews.
- Added schema versioning, WAL, atomic queue claims/result publication, persisted review states, exclusive server ownership, and interrupted-job recovery while preserving queued work.
- Added processing progress callbacks and cooperative cancellation hooks to the existing engine. Subprocess cancellation and timeouts kill/wait for the child and preserve partial-output cleanup.
- Added pinned backend dependencies and Git exclusions for SQLite WAL/SHM sidecars.
- Added focused API/store/worker tests, real media upload/render/review/revision/restart checks, and actual loopback HTTP verification.
- Verification passed a full 64-test suite in 122.720 seconds and `pip check`. After fixing stale worker health following a temporary database error, all 19 focused backend tests passed in 3.690 seconds, including the new recovery regression. The available suite now contains 65 tests.
- The Next.js dashboard and user-recording acceptance remain pending. Native speech calls observe cancellation at segment boundaries. A forced process termination can leave a child process until it exits.

## 0.3.0 — 2026-11-17

- Added `progress.md` with reading prerequisites, verified milestone history, environment details, acceptance gaps, and the M4 handoff. Added ongoing start/finish reporting instructions to `AGENTS.md` and its reading order.
- Added M3 deterministic candidate ranking using median-relative RMS peaks, audio onset, merged speech coverage, and language-specific transcript cues.
- Moved transcript generation before automatic selection for captioned jobs. Added `--speech-ranking` for transcript-aware selection with caption overlays disabled.
- Added JSON-configurable normalized weights, minimum scores, temporal gaps, interval IoU suppression, and custom per-language phrases, with `ranking.example.json` as a reference.
- Added inspectable candidate feature values, cue matches, per-feature score contributions, application version, and effective ranking settings in job manifests.
- Added labeled synthetic event fixtures and ranking regressions for multilingual token handling, quiet reactions, silence, boundary events, custom weights, thresholds, and duplicate suppression.
- Extended actual offline CLI integration coverage to select a candidate using custom transcript cues and reuse the cached transcript.
- Verification passed all 43 automated tests in 27.112 seconds, including rendering, real offline CPU inference, transcript caching, and configurable ranking through the CLI.
- Human-pick quality comparison and optional scene detection remain pending.

## 0.2.0 — 2026-11-17

- Implemented M2 multilingual CPU INT8 transcription using Faster-Whisper base, bundled speech filtering, and automatic language detection.
- Created an ignored project virtual environment, pinned the verified speech dependency set, and prepared the MIT-licensed multilingual base model with its exact source revision recorded locally.
- Fixed a real inference failure caused by Faster-Whisper 1.2.1 passing an argument removed in PyAV 19. Pinned the tested compatible PyAV 16.1.0 wheel.
- Added explicit `prepare-model`, opt-in `--captions`, optional language codes, offline model loading, and friendly missing-model/dependency errors.
- Added content/configuration-addressed transcript caching, corrupt-cache recovery, full transcript JSON, clip-relative SRT/ASS, safe subtitle formatting, and burned-in captions.
- Added unit and real inference integration coverage, Windows-generated synthetic speech, offline CLI checks, and retained synthetic preview artifacts under ignored local data.
- Verification passed across 29 tests, the FFmpeg health check, and `pip check`. Actual CPU inference recognized the locally synthesized English sample and a repeat render reused its transcript. Silent/no-audio cases completed cleanly. Rendered English, Bengali, and Arabic caption previews were inspected visually.
- Real-recording speech quality, 10-minute throughput, improved ranking, and the web dashboard remain pending.

## 0.1.0 — 2026-11-17

- Started M1 under the user's session authorization for batched verification and implementation.
- Added a standard-library Python CLI for health checks, media inspection, audio-activity candidates, and manual trimming.
- Added MP4/MKV validation, 15–60-second bounds checks, padded/cropped vertical H.264/AAC exports, and 720p/1080p output at 30/60 FPS.
- Added per-data-directory worker locking, atomic output publication, cancellation cleanup, and persistent job manifests.
- Added unit tests and synthetic-media integration checks. Synthetic fixtures are created under ignored local data and removed after each successful test.
- Speech transcription, subtitles, the web dashboard, and real-recording acceptance remain future milestones.
- Verification passed on the laptop with Python 3.14.7 and FFmpeg/FFprobe 9.0.2. The health command passed, and all 16 automated tests passed in 18.975 seconds.
- Synthetic integration coverage includes three decoded 720×1280 clips, silent/no-audio input, portrait cropping, Unicode/spaced paths, and a CLI run importing 1080p/60 FPS and exporting 1080×1920 at 60 FPS. This test-suite duration is not a real-recording throughput benchmark.
