# Testing and Acceptance Strategy

> Execute each test only after asking for specific approval as required by `AGENTS.md`.

## Hardware-specific baseline
Document laptop CPU/RAM/OS and version; video resolution/FPS/codec/duration; model and quantization settings; FFmpeg build; wall-clock runtime; peak memory; number of clips; subtitle quality. Repeat on desktop after migration.

## Test media (owned/authorized samples only)
1. 30–60s clip with clear speech and one loud reaction.
2. 60s clip with no speech or no audio track.
3. 2–3m game clip with rapid scene changes but no meaningful event.
4. 10m OBS recording with multiple interesting and boring moments.
5. MKV from OBS, MP4, portrait input, landscape input, variable frame rate if available.
6. Filename with spaces, Unicode, and long paths; test invalid/nonvideo input too.

## Unit tests
- All segment start/end values within `[0, duration]`; duration > 0.
- Clip duration settings validate min/max; near-start and near-end behavior correct.
- Normalization handles constant/silent signals without divide-by-zero.
- Candidate ranking deterministic for fixed inputs, no overlapping duplicates.
- Subtitle times monotonic and within bounds; empty transcript yields no caption overlay.
- Sanitized paths cannot escape designated output directory.

## Integration tests
- FFmpeg input -> audio extraction -> valid JSON transcript/feature events.
- Audio-only, missing-audio and silent file paths handled.
- ffprobe nonzero exit produces friendly failure; job state becomes `failed`.
- ffmpeg interrupted -> temporary files cleaned/recoverable, no falsely completed job.
- Cancelled long job stops child processes and does not corrupt SQLite.
- API rejects arbitrary file access and malformed input.

## Manual acceptance demo
**Input:** 10-minute OBS recording the user has permission to process.
**Run:** locally, offline after dependency/model installation.
**Expected:** application displays one completed or clear diagnostic job, produces **up to 3** candidate clips of 15–60s where actual events exist, vertical 720×1280 H.264/AAC, readable captions when speech exists, thumbnail/preview, editable timestamps, playable MP4 downloads. Review/edit/download fully local.

## Honest quality measurements
- Have user manually mark 5–10 meaningful events across several recordings.
- Compare top-N overlaps with the marked intervals; record precision@3 and recall (with tolerance windows documented).
- Track transcription issues, false positives from loud sound/music and false negatives from quiet meaningful moments.
- Do not label 'perfect', 'viral', or 'real-time' without evidence.

## Reproducibility report template
- Device/OS:
- Python/Node/FFmpeg versions:
- Model & settings:
- Media duration/resolution/FPS:
- Inference duration:
- Total processing duration:
- Peak RAM/CPU:
- Candidate count and timestamps:
- Subtitle issues:
- Failures/retries:
- User review and approval:

## Smart reframing extension

See SMART_REFRAMING.md for reproducible commands and manual acceptance steps; progress.md records measured results. Automated checks cover crop bounds, conservative decisions, scene smoothing, composition pixels, A/V metadata, source previews, cancellation, request validation and transcript reuse. Passing these checks does not prove semantic importance, real webcam quality or browser interaction.
