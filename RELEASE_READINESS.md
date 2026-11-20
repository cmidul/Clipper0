# CLIPPER0 RELEASE READINESS REPORT

Audit date 2026-11-20. Scope is the local working tree, including the spatial reframing changes. Historical results are identified where used.

The [release checklist](RELEASE_CHECKLIST.md) records the focused follow-up and exact Git review. The approved interactive localhost workflow passed on Edge. A fresh temporary Python environment also bootstrapped pip with the full interpreter path after the shell launch aliases failed. Clean dependency installation and upstream advisory lookup remain open.

## Verdict

**85/100 — CONDITIONALLY READY — FIX LISTED BLOCKERS FIRST.**

Recommended label after sign-off is **Windows x64 early public beta, source distribution**. Current evidence supports the core CPU workflow, manual layouts, and the tested localhost dashboard path. Fresh installation, upstream checks, and project licensing remain release gates.

| Category | Score | Verified evidence and deductions |
| --- | ---: | --- |
| Core video import, analysis, and clipping | 23/25 | Actual upload, probe, audio ranking, and rendered candidate. Up-to-10 and temporal-distribution logic passed tests. Hours-long processing remains unmeasured. |
| Video rendering and spatial framing | 18/20 | Real FFmpeg exports, comparative pixel checks, all 12 canvases for each new layout, manual still/export match, and captioned CPU rendering. Real gameplay framing and perceptual synchronization remain unmeasured for this revision. |
| User interface and workflow | 14/15 | Production build, TypeScript, helper tests, and live Edge upload, playback, framing preview, revision, download, and history reopening. Cross-browser and accessibility acceptance remain untested. |
| Stability and error handling | 13/15 | Test coverage for bad imports, cancellation/recovery, missing tools, project deletion guards, origin/host checks, and rollback. No sustained workload or independent security review in this pass. |
| Installation and portability | 6/10 | Existing Windows 11 runtime, codec health, dependency consistency, and offline model inference passed. Clean Windows installation and Windows 10 portability remain open. |
| Documentation and open-source preparation | 7/10 | Current setup, usage, demo, limitations, contribution guidance, dependency inventory, and local Git privacy checks. Owner license and upstream verification remain open. |
| Basic test coverage | 4/5 | Focused backend, actual media, frontend regression coverage, and one live browser workflow. Current full suite was not rerun. |
| **Total** | **85/100** | **The threshold is met. Release gates still apply.** |

## Feature audit

| Feature | Status | Code and evidence |
| --- | --- | --- |
| Video import and validation | Implemented and tested | `api.py::import_upload`, `service.py::import_local`, `engine.py::inspect_media`. Actual MP4 upload and malformed input handling. Managed copies and size, duration, container, and stream checks are in place. |
| Long-video processing and chunking | Partially implemented | `engine.py::audio_activity` streams activity data. `ranking.py::rank_candidates` spreads selected candidates across temporal chunks in long recordings. Synthetic long-timeline tests passed. Full multi-hour inference and resource use remain unverified. Temporal selection does not split the entire job into restartable chunks. |
| Highlight detection and ranking | Implemented and tested | `ranking.py::rank_candidates` and `engine.py::process`. Synthetic audio event generated a candidate through the API. Ranking and offline speech tests cover evidence, thresholds, and quiet inputs. Human quality measurements remain open. |
| Configurable 1–10 clips | Implemented and tested | `JobOptions`, CLI `--count`, `rank_candidates`, dashboard selector. Range and long-timeline distribution tested. This audit generated one ranked clip in its focused workflow. |
| Temporal clipping and FFmpeg export | Implemented and tested | `engine.py::render_clip` publishes completed MP4 output. FFprobe and decode checks verified export duration, H.264/AAC, square pixels, and stream timing. |
| Focus Crop | Implemented and tested | `reframing.py::crop_for_focus` and `composition.py::build_filtergraph`. Crop stayed in source bounds and enlarged the selected edge in an actual MP4. |
| Hybrid Focus | Implemented and tested | Same geometry and graph path, with a wider source region fitted over blur or padding as needed. FFmpeg pixel checks showed a larger foreground than Full Frame. |
| Full Frame and streamer split | Implemented and tested | `build_filtergraph`, `build_initial_plan`. Synthetic clips preserve edge markers in Full Frame and show the selected webcam panel in split. Real automatic webcam detection remains untested for this revision. |
| Manual focus, region, and zoom | Implemented and tested | `FramingEditor.tsx`, `web/lib/framing.ts`, `build_initial_plan`. Edge bounds, region retention, zoomed crop, and saved revision options tested. The browser run exercised position and zoom sliders. Pointer-region and keyboard acceptance remain open. |
| Automatic focus tracking | Implemented and tested | `vision.py::analyze_candidate`, `analyze_frames`, `smooth_track`, and `plan_from_analysis`. Tests cover cache, scene resets, confidence fallbacks, bounded tracking, and static overrides. These heuristics have no measured real-gameplay accuracy for this revision. |
| Subtitles and positioning | Implemented and tested | `speech.py::transcribe_media`, `write_subtitles`, `engine.py::render_clip`. Actual offline English fixture inference and captioned export checks passed. A layout-aware position is available. Dynamic HUD avoidance and multilingual visual review remain open. |
| Aspect ratio, resolution, and compression | Implemented and tested | `engine.py::output_dimensions`, `compression_crf`, API models, and `web/lib/api.ts`. FFprobe verified 24 one-frame H.264 encodes across Focus Crop and Hybrid Focus. Representative 15-second exports also passed. |
| Preview, rerender, and download | Implemented and tested | `service.py::frame_preview` and `vision.py::plan_candidate_framing` share the export plan and composition graph. Manual still and export matched by decoded pixels. Verified browser playback, revision, download and saved settings, plus API byte ranges and transcript reuse. Moving-track still parity remains unverified. |
| History, archive, and deletion | Implemented and tested | `store.py`, `service.py::delete_project_assets`. Archive/restore persists, active jobs block cleanup, and tests protect original files, other projects, shared caches, and hard links. |
| Job progress and errors | Implemented and tested | `Service.execute`, `Service.work`, `Store.finish`. Automated checks cover job states, progress, cancellation races, storage failures, recovery, and output publication. |
| Local installation and portability | Partially implemented | Python manifests, npm lock, and `AUTOCLIP_*` environment settings are in place. Existing Windows 11 runtime passed health checks and the dashboard built. Clean install, Windows 10, and other platforms remain unverified. |

## Fixes and test evidence

- Completed the working-tree Focus Crop/Hybrid Focus integration through the planner, FFmpeg graph, queued composition preview, and dashboard editor. Kept existing saved modes, settings, and job data.
- Fixed manually positioned Auto zoom being ignored at non-default magnification. Fixed the sample resolution bound so portrait source analysis also stays within 640 pixels per edge.
- Updated the API schema regression for the new persisted framing fields. Added focused checks in `test_backend_integration.py`, `test_composition_integration.py`, `test_reframing.py`, and `web/tests/framing.test.ts`.
- Backend passes were separate and overlap. The initial engine/ranking/framing/revision group passed 104 tests, the API/preview/project group passed 18, the updated planner/vision/composition group passed 38, the speech/render group passed 12, the matrix and geometry group passed 4, and the final backend/store/option group passed 40. A test selection initially named a nonexistent class and was rerun with the correct class. The current full discovery suite was not rerun.
- Frontend passed 12 Node tests, TypeScript, and the production Next.js build. Installed Python dependency consistency and FFmpeg/FFprobe health passed.
- The disposable 20-second fixture produced a ranked 15-second candidate and a modified focus revision through the actual dashboard in headless Microsoft Edge 158.0.4370.33 using isolated loopback services and a fresh project database. Playback advanced and sought, the exact still loaded, the revision played, and the browser saved an MP4 byte-for-byte identical to the render. A reload restored both jobs and the Focus Crop revision at 1.5× zoom.
- FFprobe verified 480×854 H.264/AAC, square pixels, and matching 0.000-second starts and 15.000-second durations. The MP4 fully decoded, and the still matched the revised frame with a mean absolute pixel difference of 0.63 on a 0–255 scale. The blue source marker enlarged as expected. The fixture hash was unchanged.
- The first browser attempt tried selecting the fixture before React connected to the processor and timed out before upload. The automation was corrected to wait for the connected indicator. Every step on the second attempt passed. The temporary services were stopped and both ports were free afterward.

## Remaining gaps

- The approved desktop-size Edge workflow passed. Keyboard accessibility, pointer-region behavior, other browser engines, and captions in the interactive browser workflow remain unverified.
- Real gameplay comparison for the current layouts remains pending. No measured ranking precision, automatic subject tracker accuracy, 10-minute OBS acceptance, multi-hour benchmark, or desktop throughput claim is supported.
- Smart layouts require unrotated square-pixel source video. Multilingual recognition and text readability depend on the audio and installed fonts. Composition stills show caption guides rather than timed glyphs. Semantic object/HUD understanding and dynamic HUD avoidance are outside the current feature set.
- No unresolved failure from the completed targeted regressions is known. Fresh-machine setup and current upstream security advisories have not been verified.

## Installation, performance, and source hygiene

- Verified on the existing Windows 11 x64 laptop environment with Python 3.14.7, Node.js 24.15.0, npm 11.12.1, and FFmpeg/FFprobe 9.0.2. The preceding laptop handoff records an Intel Core i5-1145G7 and 16 GB RAM. The Ryzen 5 5600G / Windows 10 target is unverified.
- Rendering and visual analysis used CPU. Short tests used a single worker and bounded FFmpeg threads. No controlled peak memory, wall-time benchmark, or throughput measurement was taken for the new layouts. Historical timing in the handoff belongs to an earlier revision.
- The [README](README.md) documents install, offline model preparation, usage, demo, and troubleshooting. [.env.example](.env.example) covers overrides. [.gitignore](.gitignore) rejected representative media, weights, database, environment, and dependency paths.
- Reviewed tracked filenames across locally available Git history and searched tracked content for common private keys and token patterns. No matches for those checks. These checks are bounded to the local refs and patterns inspected.
- [Third-party notices](THIRD_PARTY_NOTICES.md) record installed licenses, the model provenance, and the GPL FFmpeg build boundary. Source installs obtain executables and weights separately. Upstream license and current advisory verification are pending. The project has no approved license file yet. No push, tag, visibility change, or publication was made by this audit.

## Required before publication

1. Reproduce the README install from a clean Windows 11 checkout with only the listed prerequisites. Record dependency resolution, model preparation, offline startup, and a short render. Keep Windows 10 listed as unverified until a separate check passes.
2. Verify upstream package and model notices and current advisories for the pinned versions. Resolve any blocking finding. Choose and explicitly approve the Clipper0 license, then add its file to the reviewed source.
3. Review the exact release diff and intended publication ref. Publish the source and announcement only after explicit owner approval. Limit the beta announcement to the checks that passed.
