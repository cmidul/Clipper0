# Clipper0 — Agent Guide Pack

A **zero-paid-API, local-first** gaming highlight clipping project. The Python CLI validates media, ranks candidates using audio and optional speech evidence, trims clips, and renders portrait or landscape videos with optional local multilingual transcription and burned-in captions. A localhost API and web dashboard provide managed imports, durable queued jobs, review, rerendering, preview, and downloads.

## Smart reframing

The dashboard now provides Auto, smart tracking crop, streamer/gameplay split, full-gameplay blur/pad, manual focus/webcam selection, source-frame previews, caption placement and cached framing revisions. See [SMART_REFRAMING.md](SMART_REFRAMING.md) for setup, architecture, limitations and manual tests.

## Recording projects

**New recording** opens an empty workspace. Use **Choose recording** to open the file picker, or drop an MP4 or MKV onto the upload area. Selecting a file prepares it for import. A saved entry appears when the recording is imported, and jobs already submitted keep running when you move to another workspace.

Use the three-dot control beside a recording to manage that project:

- **Remove from History** moves it to **Archived Projects**. Its recording, files, and jobs are preserved. Select **Restore** to bring it back, including after an app restart.
- **Delete Project Files** permanently removes the managed recording copy and recognized job outputs, including MP4 clips, captions, saved job transcripts, preview frames, manifests, and eligible partial files. Original recordings and shared analysis caches are preserved. Queued or running jobs, including frame previews, block cleanup until they stop. The project and job history remain visible with **Assets Deleted** after cleanup. If cleanup cannot remove a file, the dialog names it and the project shows **Deletion Incomplete**. Close any program holding the file open and retry where appropriate. Reimport the original recording to create a new project with available assets.

The processor upgrades existing project databases to schema version 2 on startup. Keep a backup before migrating if you need to reopen the database with an older version.

To verify the dashboard with two disposable test recordings:

1. Open a project and select **New recording** during or after processing. The workspace clears and the file picker stays closed. Reopen the project to check its jobs. Select **Choose recording** and confirm the picker opens.
2. Use Tab and Enter to open a project's three-dot control and **Remove from History** dialog. Press Escape or select **Cancel** and check that the project stays visible. Confirm the action, restart the app, and restore the project from **Archived Projects**. Check that its clips still play.
3. Open **Delete Project Files** and confirm the dialog names the intended project and focuses the cancel button. Cancel first and verify the project still plays. Try again while a job is active and confirm deletion is blocked. Once the job stops, confirm deletion of the disposable project's managed files. Verify the history label, the untouched original, and playback in the second project.

## Dashboard aspect ratio

In **Clip settings → Aspect ratio**, choose **9:16 Portrait** or **16:9 Landscape** before generating candidates or rendering a manual interval. Resolution labels update to match the selected ratio. The default remains portrait; older jobs without a ratio also retain portrait behavior.

| Ratio | 720p output | 1080p output |
| --- | --- | --- |
| 9:16 Portrait | 720 × 1280 | 1080 × 1920 |
| 16:9 Landscape | 1280 × 720 | 1920 × 1080 |

**Fit full frame** adds padding as needed; **Center crop** fills the selected shape by cropping centrally. Captions use matching output coordinates and scaled font/margins. Under **Adjust clip**, the revision has its own aspect-ratio choice, initially matching the original job. Changing a revision's draft settings does not reshape the existing video preview. A new render appears in a new job; the original remains available.

With the existing project dependencies installed and a successful frontend build, start the backend from the repository root:

```powershell
.\.venv\Scripts\python.exe -m autoclip serve
```

In a second terminal opened in `web/`, start the frontend:

```powershell
npm.cmd run start
```

Open `http://127.0.0.1:3000`. After source changes, stop the frontend before running `npm.cmd run build` in `web/`, then restart it. Restart the backend after Python source changes. Follow AGENTS.md and its active exceptions when performing these actions through an agent.

For the CLI, use `--aspect-ratio 16:9` or `--aspect-ratio 9:16`. The API accepts the same string as `aspect_ratio` in new-job and revision requests; a revision inherits the previous ratio when omitted.

Manual regression check: import an authorized recording at least 15 seconds long, choose a manual 15-second interval and 16:9, render, download, and confirm the dimensions in a media player. Repeat with 9:16. Try both resolutions and fit/crop layouts, inspect captions where speech exists, then change a completed clip's ratio under Adjust clip and render a revision. Refresh and confirm both jobs and their original shapes persist. Browser UI acceptance must be recorded separately from automated rendering/API tests.

## Quick start
1. Unzip the pack into an empty project folder and open that folder in VS Code.
2. Give your coding agent the first prompt in `PROMPTS_FOR_AGENT.md`.
3. Insist the agent follow `AGENTS.md` — it must obtain permission **before every individual edit, command, execution, install, test, Git action**.
4. Supply your laptop CPU, RAM, OS and disk specs when requested.
5. Build and fully test locally on laptop, then use `GITHUB_MIGRATION.md` to transfer code to desktop.

## Documents
- `AGENTS.md` — primary operating rules and mandatory per-action Yes/No gate.
- `PROJECT_BRIEF.md` — goals, user stories, scope and exclusions.
- `ARCHITECTURE.md` — components, data contracts, scoring and APIs.
- `IMPLEMENTATION_PLAN.md` — staged agent tasks and deliverables.
- `TESTING_AND_ACCEPTANCE.md` — test cases, quality metrics and demo target.
- `SETUP_LAPTOP.md` — preflight, dependencies and first-device setup.
- `GITHUB_MIGRATION.md` — Git privacy and desktop deployment.
- `COST_AND_PERFORMANCE.md` — no token charges, performance tradeoffs.
- `PROMPTS_FOR_AGENT.md` — ready-to-paste VS Code agent prompts.
- `.github/copilot-instructions.md` — additional Copilot instructions.
- `.gitignore` and `.env.example` — repo hygiene templates.

## MVP goal
10-minute OBS input -> up to 3 candidate 15–60s highlight clips, vertical MP4 with captions when there is speech, browser preview/edit/download, all local. Proposed moments are heuristic candidates, **not guaranteed viral clips**.

## Explicitly pending
The dashboard source is implemented. Interactive browser acceptance, a full 10-minute OBS acceptance run, human-pick comparison and desktop migration remain pending. Smart-reframing checks and measured local comparisons are recorded in progress.md.

## Run the M1 clipping engine

Requires Python 3.11 or newer and FFmpeg/FFprobe on PATH. M1 uses only Python's standard library. The laptop environment uses Python 3.14 and FFmpeg 9. Speech dependencies are pinned and verified in the project virtual environment on this Windows 11 laptop.

Run from the project root in PowerShell. Use recordings you own or have permission to process.

```powershell
python -m autoclip health
python -m autoclip inspect "C:\path\to\recording.mkv"
python -m autoclip clip "C:\path\to\recording.mkv" --count 3 --length 30
```

The last command prints the path to a local JSON manifest. Its sibling `clip-01.mp4` files can be opened in a media player. Each manifest includes source duration, settings, timestamps, audio evidence, review state, and elapsed processing time. These scores rank audio activity. Human review determines which moments are worth keeping.

Default output is padded 720×1280 at 30 FPS, preserving the whole source frame. Choose `--layout crop` for a centered crop, `--resolution 1080` for 1080×1920, or `--fps 60` for 60 FPS. Manual trimming also works for recordings without audio.

```powershell
python -m autoclip clip "C:\path\to\recording.mp4" --start 10 --end 30 --layout crop
```

Manual ranges must be within the recording and span 15–60 seconds. Automatic selection returns up to three nonoverlapping candidates. Silence, steady audio, missing audio, and recordings under 15 seconds can return a completed job with zero candidates and a diagnostic.

Local output defaults to ignored `local-data/`. Override it through the `AUTOCLIP_DATA_DIR` environment variable. Executable overrides are `AUTOCLIP_FFMPEG_PATH` and `AUTOCLIP_FFPROBE_PATH`. `AUTOCLIP_WORKER_THREADS` defaults to 4. M1 reads process environment variables directly. `.env.example` is a reference and is not loaded automatically.

Only one job runs per data directory. Press Ctrl+C to cancel. Finished clips remain available, interrupted partial clips are removed, and the manifest records cancellation or failure. A forced process termination may leave an unfinished job directory for inspection. Limits are 100 GiB, four hours, and 8192 pixels per dimension.

## Reproduce M1 checks

```powershell
python -m unittest discover -s tests -p test_engine.py -v
python -m unittest discover -s tests -p test_integration.py -v
```

Integration checks generate synthetic videos under ignored `local-data/test-runs/`, exercise MKV/MP4 inputs, Unicode/spaced paths, three audio candidates, vertical rendering, and no-audio handling. They decode rendered clips to check for playback errors.

The laptop verification run on 2026-11-17 passed the health command and all 16 automated tests in 18.975 seconds. It also verified the CLI using a synthetic 1080p/60 FPS input and 1080×1920/60 FPS output. Synthetic tests establish processing behavior. Actual OBS footage still needs quality and throughput measurements.

For manual acceptance, inspect a short authorized recording, render candidates, open each output, and compare timestamps, layout, and sound with the original. Try manual trimming and Ctrl+C during a longer render. Record real processing time and quality before proceeding to speech and dashboard acceptance.

## M2 multilingual speech and captions

The laptop already has a project virtual environment and the multilingual `base` model prepared. Use the virtual environment's Python for captioned jobs.

```powershell
.\.venv\Scripts\python.exe -m autoclip clip "C:\path\to\recording.mkv" --captions
.\.venv\Scripts\python.exe -m autoclip clip "C:\path\to\recording.mp4" --start 10 --end 30 --captions --language bn
```

`--captions` enables CPU INT8 Faster-Whisper with automatic language detection, one worker, four CPU threads, beam size 1, and speech activity filtering. `--language` optionally supplies a Whisper language code. The model recognizes Whisper's supported languages. Accuracy on noisy audio and mixed-language speech needs evaluation with your recordings.

The job directory contains `transcript.json`, clip-relative `.srt` and `.ass` files where speech overlaps a clip, and the rendered MP4 with burned-in captions. Silent/no-audio inputs finish with `caption_status` set to `no_speech`. Clips without overlapping speech have no caption overlay. Captioned jobs use their transcript during candidate ranking. A steady spoken recording without a supported reaction cue or an audio event can return zero candidates. Manual timestamps let you render a specific speech excerpt.

Model loading and inference use local files only. The separate preparation command requires internet for the initial download. To recreate this environment on another Windows machine, verify Python and wheel support, then run these commands from the project root.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-speech.txt
.\.venv\Scripts\python.exe -m autoclip prepare-model
.\.venv\Scripts\python.exe -m pip check
```

`AUTOCLIP_MODEL_SIZE` supports multilingual `tiny`, `base` (default), and `small`. Changing it requires preparing that model. Models are stored under `AUTOCLIP_MODEL_CACHE_DIR` or `local-data/models/`, with source repository, exact download revision, and MIT license recorded locally. The environment, models, transcripts, and generated media are ignored by Git.

Transcripts are cached under `local-data/transcripts/` using the full media content hash, model file hashes, language, inference settings, and speech runtime versions. Timestamp edits reuse the same transcript. A corrupt cache is regenerated. Captions use segment-level timing and system font fallback. `AUTOCLIP_CAPTION_FONT` selects a font family. For Bengali or another script, verify that an appropriate font is installed. SRT preserves escaped text, while ASS displays fullwidth braces/backslashes to prevent caption text from being interpreted as formatting commands.

## Verify M2

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Speech unit checks cover clipped/rebased timestamps, special characters, missing models, cache reuse and invalidation, corrupt caches, and job failure status. Integration checks exercise the actual CLI, local CPU model, English speech recognition, silent audio, captioned exports, and cache reuse with offline mode enabled. The model must be prepared for real inference tests. On Windows, the spoken fixture uses an installed English system voice. Its first generation may require system access outside an agent sandbox.

Synthetic speech samples and caption preview PNGs remain under ignored `local-data/speech-smoke/` for inspection. For manual acceptance, render a user-owned spoken clip using `--captions`, open the MP4 and SRT, and compare words, timing, glyphs, and readability with the source. Rerender a different interval and confirm `transcript_cache_hit` in the manifest. Repeat with silent audio and noisy/multilingual recordings. Real multilingual recognition quality and 10-minute OBS performance remain unmeasured.

## M3 candidate ranking

Captioned jobs now transcribe before selection and rank the candidates using audio plus transcript evidence. Use `--speech-ranking` to enable the same speech analysis with caption rendering disabled. Omitting both flags uses audio-only ranking and keeps speech dependencies optional.

```powershell
.\.venv\Scripts\python.exe -m autoclip clip "C:\path\to\recording.mkv" --captions
.\.venv\Scripts\python.exe -m autoclip clip "C:\path\to\recording.mkv" --speech-ranking --ranking-config ranking.example.json
```

Each candidate has a normalized weighted score between 0 and 1. The manifest includes the application version, effective settings, feature values, matched phrases and their language, event timestamp, and each feature's weighted contribution. The score is a deterministic heuristic.

| Feature | Calculation | Default weight |
| --- | --- | --- |
| `audio_peak` | Positive event RMS above the recording median, divided by maximum RMS minus that median | 0.45 |
| `audio_onset` | Positive RMS rise from the previous second, divided by maximum RMS | 0.20 |
| `speech_activity` | Fraction of the candidate interval covered by speech, merging overlapping segments | 0.10 |
| `transcript_cues` | 1 when a configured phrase matches within an overlapping speech segment, otherwise 0 | 0.25 |

Weights are divided by their total before scoring. Silent and constant signals produce zero peak/onset features without division by zero. Audio events require RMS at least 0.005 and at least 1.25 times the recording's mean RMS. Cue matches can independently propose an event at a speech segment's midpoint. Matching uses Unicode-normalized whole tokens and retains combining marks for Bengali and Hindi. Cue repetition does not multiply the cue feature.

The small default cue lists cover English, Bengali, Hindi, Spanish, and Arabic. Other Whisper languages still get speech coverage and audio features. Add language-specific phrases through the JSON configuration. These initial lists and weights require evaluation on your footage.

`ranking.example.json` demonstrates `weights`, `min_score` (default 0.25), `min_gap_seconds` (default 2), `max_iou` (default 0.2), and per-language `cues`. Partial weight changes merge with defaults. A supplied language list replaces that language's default phrases. An empty list disables its cues. Unknown fields and invalid settings return a clear error.

Candidates are sorted by score with deterministic timestamp tie breaks. Interval intersection-over-union suppression and the default two-second gap remove overlapping/adjacent duplicates. Setting the gap explicitly to zero permits partial overlap up to the configured IoU limit. IoU must remain below 1 so identical windows are always suppressed. Scores below the threshold produce zero candidates. Manual timestamp selection bypasses ranking.

## Verify M3

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_ranking.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The labeled synthetic cases in `tests/fixtures/ranking_cases.json` cover separated audio events, quiet Bengali speech cues, ordinary speech over steady audio, adjacent duplicate reactions, and silence. Tests also cover custom language phrases, weight/threshold changes, score contributions, fractional media duration, transcript validation, and the actual offline speech-ranking CLI with cached transcription.

For manual quality evaluation, mark 5–10 meaningful event timestamps in authorized recordings before inspecting generated candidates. Compare the audio-only and speech-enabled runs with identical clip length/count. Match each returned clip to at most one marked event within its interval. Record matched clips divided by returned clips as precision, and distinct matched events divided by marked events as recall, reporting zero-result cases separately. Note false positives from music/cue words and missed quiet events. Human-pick metrics and optional scene detection remain pending.

## M4 backend and durable queue

The backend portion of M4 is implemented. Its browser dashboard and full 10-minute OBS acceptance remain pending. Install the backend dependency set when recreating the environment, then start the API.

```powershell
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-backend.txt
.\.venv\Scripts\python.exe -m autoclip serve
```

The command binds to `127.0.0.1:8000` and starts one background worker. `--port` changes the port. Check `http://127.0.0.1:8000/health` for tool/worker status. `GET /openapi.json` describes the API contract. The API works locally without external documentation assets.

The server copies imports into the configured data directory, validates the media, computes its SHA-256 hash, and returns a media ID. Browser/file uploads use raw video bytes as the request body and a basename in the `filename` query parameter.

```powershell
curl.exe --request POST --data-binary "@C:\path\to\authorized-recording.mkv" "http://127.0.0.1:8000/media/import?filename=recording.mkv"
```

Use the returned ID when creating a job from another PowerShell terminal.

```powershell
$jobBody = @{ media_id = 'PASTE_MEDIA_ID'; max_clips = 3; clip_length = 30; captions = $true } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/jobs' -ContentType 'application/json' -Body $jobBody
```

### API routes

| Method and route | Behavior |
| --- | --- |
| `GET /health` | Verify FFmpeg/FFprobe availability and background worker health |
| `POST /media/import?filename=recording.mkv` | Stream a raw MP4/MKV body into validated managed storage |
| `POST /media/import-local` | Copy a basename from the configured recordings directory, using JSON `filename` |
| `GET /media` and `GET /media/{id}` | List or inspect imported media metadata |
| `POST /jobs` | Queue a job using a media ID and validated options |
| `GET /jobs` and `GET /jobs/{id}` | Read persisted state, phase, coarse progress, errors, options and final caption metadata |
| `POST /jobs/{id}/cancel` | Cancel a queued job immediately or request cancellation of a running job |
| `GET /jobs/{id}/candidates` | Read ranked candidates, evidence, review state and clip URLs |
| `PATCH /candidates/{id}` | Set JSON `review_state` to proposed, approved or rejected |
| `POST /candidates/{id}/render` | Queue a revision using JSON `start`, `end` and optional `layout_mode` / `aspect_ratio` |
| `GET /clips/{id}/preview` | Stream an MP4 with byte-range playback support |
| `GET /clips/{id}/download` | Download the rendered MP4 |
| `GET /clips/{id}/subtitles` | Download the clip's SRT where captions exist |

Media/job list routes accept `limit` (1–100) and `offset`. Job options include `max_clips`, `clip_length`, `layout_mode`, `aspect_ratio`, `resolution`, `fps`, `captions`, `speech_ranking`, `language`, and optional manual `start`/`end`. Defaults match the CLI. Manual intervals must stay within the imported recording and span 15–60 seconds. Status responses expose the normalized engine options with `count` and `layout` keys.

Rerendering creates a new job and candidate linked by `source_candidate_id`. The previous render and its review state remain available. Review states persist across restarts. Candidate files are published through the API only after a job completes and its result transaction commits.

### Storage, progress and recovery

SQLite schema version 1 stores media, jobs, candidates and clip records under `AUTOCLIP_DB_PATH`, defaulting to `local-data/autoclip.sqlite3`. It uses WAL, per-operation connections, foreign keys, transactional job claims and atomic result publication. The server has its own ownership lock so a second server cannot recover or claim another live server's jobs.

Uploads use random managed filenames and enforce the configured size limit while streaming. Failed uploads remove their staging files. Local import accepts a single basename under `AUTOCLIP_RECORDINGS_DIR`, defaulting to `local-data/recordings`. It checks that the source stayed unchanged during the copy. Set that directory to an authorized completed-recording folder if needed. Clip assets are resolved within managed storage. Allowed browser origins are the local API and the planned localhost port-3000 frontend.

Progress percentages represent processing stages and completed clips. They provide coarse feedback. Poll status until the state is completed, failed or cancelled. Running jobs stay below 100 percent until result publication commits.

Cancellation polls during FFmpeg execution and stops/waits for the child process before removing its partial output. Speech processing checks between file-hash blocks and recognized segments. An active native inference call may finish before cancellation is observed. A running job reports `cancel_requested` until the worker reaches a terminal state. Ctrl+C shuts down the server and requests cancellation of its active job. Queued jobs persist.

On restart, queued jobs resume processing. Jobs left running after an interruption become failed with a diagnostic, or cancelled when a cancellation request was outstanding. Submit a new job for the imported media to retry. An interrupted run's private output directory may remain for inspection. A forced process termination can also leave a child process until it exits. Graceful cancellation and shutdown are covered by the processing cleanup code.

### Verify the backend

The complete suite now requires both speech and backend dependencies. Initial model preparation and the Windows voice fixture requirements from M2 still apply.

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_backend.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_backend_integration.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_backend_http.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Backend checks cover streamed size limits, copied imports, request validation, origin/host restrictions, safe assets, byte ranges, review/rerender operations, concurrent claims, result rollback, cancellation races, subprocess cleanup/timeouts, restart state, real synthetic rendering and actual loopback HTTP startup/shutdown.

For manual verification, start the API, import an authorized recording, create and poll a job, inspect candidates, open a preview URL and download a clip. Approve a candidate, queue a timestamp revision, and check that both versions remain accessible. Cancel another queued/running job and verify its terminal state. Restart the server and confirm that completed results and review states persist. Browser-dashboard acceptance follows the frontend implementation.
