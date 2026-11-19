# Architecture and Data Contracts

## Implemented reframing extension

See [SMART_REFRAMING.md](SMART_REFRAMING.md) for exact functions, current data flow and limitations. The existing single-worker queue runs selected-interval OpenCV analysis after highlight selection, then validated crop/layout plans before FFmpeg composition and caption burn-in. Revision jobs reuse trusted parent transcripts; frame previews share the queue. No database migration or external inference service is added. The initial specification below is retained as design history; implemented API routes live in autoclip/api.py.

## Local system diagram

```text
OBS / authorized video file (.mkv/.mp4)
    | import
Next.js + TypeScript + Tailwind (localhost:3000)
    | HTTP request / job polling (same machine)
Python FastAPI (127.0.0.1:8000)
    | SQLite queue + job state (one worker)
    |--> ffprobe: inspect streams and duration
    |--> ffmpeg: extract 16 kHz mono audio + thumbnails
    |--> Silero VAD / Faster-Whisper CPU INT8: speech + timestamps
    |--> NumPy/librosa: audio activity (RMS, peaks, dynamics)
    |--> PySceneDetect/OpenCV: optional reduced-frame scene cues
    |--> deterministic scoring / overlap suppression
    |--> ffmpeg: trim, pad or crop 9:16, encode H.264 + AAC
    |--> SRT/ASS subtitles; FFmpeg burn-in via libass
    `--> SQLite: jobs, segments, clips, scores, errors
Local browser: status, preview, adjust/re-render, download
```

## Platform boundaries
- UI: input, dashboard, playback and rendering settings. Do not put ML inference in Node.js.
- API: validate paths/files, create/status/cancel jobs, expose assets safely. Listen on localhost only.
- Worker: one queued job, staged progress, cancellation, logs and retryable failures. Long jobs must not block HTTP handlers.
- Storage: laptop path configurable via env/config; desktop HDD destination configurable after GitHub migration. Do not hardcode D:.
- DB: SQLite with migrations and single-process writer or safe locking. Do not put binary files in SQLite.

## Model and algorithm decisions (initial)
- `faster-whisper` model `base` **multilingual**, `device=cpu`, `compute_type=int8`, `cpu_threads` configurable (start 4 on laptop until measured; 6 on desktop), `num_workers=1`.
- Speech VAD: Silero ONNX CPU OR Faster-Whisper `vad_filter=True` initially; avoid redundant segmentation on first slice. If standalone VAD is adopted, document why.
- `beam_size=1` initially for speed; evaluate transcription quality and adjust.
- `PySceneDetect` ContentDetector on downscaled or sparsely sampled frames; optional in first release.
- Speech timestamps from Faster-Whisper. Word-level alignment may be enabled after benchmarking; don't falsely claim word-perfect sync.
- No paid LLM, remote transcription or GPU acceleration in required architecture.

## Candidate generation algorithm (initial specification)
1. Divide audio into small windows and derive normalized RMS peaks, sudden-onset intensity and speech activity.
2. Use transcript timing for cue words and unusual emotional reactions; cues are language-dependent. Do not equate loudness with quality.
3. Collect visual scene/activity changes; avoid mistaking transitions for exciting gameplay.
4. Generate candidate events with center timestamps, expand to configurable 15–60s intervals; clamp to media duration.
5. Score candidates using transparent weighted features (weights TBD through tests, not asserted as trained model).
6. Deduplicate candidates using interval overlap/IoU and minimum temporal separation.
7. Select up to N candidates with a configurable threshold; if none exceed threshold, return 'no good candidate' rather than manufacturing highlights. Optional low-confidence fallback needs explicit UI label.
8. Keep evidence per clip (`audio_peak`, `speech_activity`, `transcript_cues`, `scene_change`, confidence/heuristic score).

## Proposed database records
- `Media`: id, original_filename, stored_path, sha256, duration_ms, codec, width, height, audio_present, imported_at.
- `Job`: id, media_id, state [queued|running|completed|failed|cancelled], phase, progress_pct, error_code, error_message, created_at, started_at, finished_at.
- `SpeechSegment`: id, media_id, start_ms, end_ms, text, language.
- `Candidate`: id, job_id, start_ms, end_ms, score, evidence_json, review_state [proposed|approved|rejected].
- `Clip`: id, candidate_id, clip_path, subtitle_path, width, height, duration_ms, render_state.

## Original API sketch (implemented routes differ; see autoclip/api.py)
- `GET /health`: tool/environment check.
- `POST /media/import`: import local file or multipart upload (prefer server-side file-picker plus copy into safe directory; validate both).
- `POST /jobs`: `media_id`, `max_clips`, `min_duration_sec`, `max_duration_sec`, `layout_mode`.
- `GET /jobs/{id}`: stage, percent, errors.
- `POST /jobs/{id}/cancel`: best-effort cancellation.
- `GET /jobs/{id}/candidates`: ranked segments with evidence.
- `POST /candidates/{id}/render`: validated new start/end and crop/pad settings.
- `GET /clips/{id}/download`: safe local file streaming.

## Technical risk notes
- FFmpeg subtitle filter availability depends on build (`libass`). Check before invoking.
- Subprocess commands must use argument arrays and never interpolate unchecked paths into a shell.
- OBS can output MKV; FFmpeg supports MKV directly, and optional remux doesn't require full re-encode.
- For landscape gameplay, center cropping can lose important details; offer blurred/padded background or manual crop region.
- Recording and CPU analysis together may overload low-power laptops; first test post-recording.
