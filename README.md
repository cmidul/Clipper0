# Clipper0

Clipper0 turns owned or authorized MP4 and MKV recordings into short highlight candidates. The dashboard, FFmpeg rendering, speech transcription, and visual reframing run locally on CPU. Initial dependency and model downloads require internet. There are no paid API calls.

## What you can do

- Rank up to 10 candidate clips of 15–60 seconds, or specify a manual interval. Ranking uses audio peaks, optional speech cues, and temporal coverage on long recordings. Review the suggested moments yourself.
- Export H.264 MP4s in 9:16, 16:9, 1:1, or 4:5 at 480p, 720p, or 1080p. Aspect ratio, resolution, and compression are separate controls. A larger export can upscale the source and preserves only the detail already present.
- Reframe with **Focus Crop**, **Hybrid Focus**, **Full Frame**, or **Auto**. Use **Adjust** in the Highlight Bin to open the clip Inspector. Set a focus point or region, adjust zoom, then choose **Render revision** in the toolbar. Read the [framing guide](SMART_REFRAMING.md).
- Generate multilingual captions with an optional local Faster-Whisper model. Download the video and SRT when available.
- Reopen a project, review candidates, and download previous versions. Archiving keeps managed files. **Delete Project Files** removes recognized managed copies and exports while preserving the original source recording.

## Tested environment

Development and current regression checks use 64-bit Windows 11, Python 3.14.7, Node.js 24.15.0, npm 11.12.1, and FFmpeg/FFprobe 9.0.2 with x264, AAC, and libass. CPU-only tests run on an Intel Core i5-1145G7 with 16 GB RAM. A dedicated GPU is optional. Windows 10 x64 is a target awaiting fresh-install validation. macOS and Linux are unverified.

There is no measured minimum hardware specification. The managed import needs space for a second copy of the source, plus working files, models, and exports. Use an SSD when possible. OBS is optional and supplies recordings independently of Clipper0.

## Install on Windows

Open PowerShell in the project folder. Have 64-bit Python 3.14, Node.js 24, and FFmpeg/FFprobe on PATH. Use a build that includes the `libx264` encoder and the `subtitles` filter.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-backend.txt -r requirements-speech.txt -r requirements-vision.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m autoclip health
```

If the `py` launcher is unavailable, confirm the installed interpreter reports Python 3.14 and use its full executable path for the first command, for example `& 'C:\path\to\Python314\python.exe' -m venv .venv`. Then continue with the project environment as shown above.

To enable captions and speech-aware ranking, prepare the multilingual model once while online. The default model is `base`. The optional `AUTOCLIP_MODEL_SIZE` environment variable selects `tiny`, `base`, or `small`. Prepare the selected model before changing to offline use. Leave captions and speech-aware ranking disabled if you skip this step.

```powershell
.\.venv\Scripts\python.exe -m autoclip prepare-model
```

Build the dashboard using the pinned npm lockfile.

```powershell
Set-Location web
npm.cmd ci
$env:NEXT_TELEMETRY_DISABLED = '1'
npm.cmd run build
```

[.env.example](.env.example) is a reference for process environment variables. PowerShell does not load it automatically. Set overrides in the backend terminal before launching. Keep the default loopback bindings.

## Start and try a short recording

In a terminal at the project root, start the processor.

```powershell
.\.venv\Scripts\python.exe -m autoclip serve
```

In a second terminal in `web`, start the dashboard.

```powershell
$env:NEXT_TELEMETRY_DISABLED = '1'
npm.cmd run start
```

1. Open `http://127.0.0.1:3000` and choose a 20–60-second recording with a clear audio event.
2. Choose a shape, resolution, and framing mode. Select **Generate candidates**. If nothing ranks, choose a manual 15–60-second interval.
3. Select a result in the **Highlight Bin** and play it in the **Monitor**. Choose **Adjust**, select **Focus Crop**, then set a focus point and zoom and request a composition preview. The preview shows framing and caption guides. The final MP4 includes burned-in captions when speech is available.
4. Render the revision and compare it with the original. Download the MP4, reload the dashboard, and check the saved project and revision.
5. Stop both terminals with Ctrl+C when finished. Let the worker finish handling cancellation before closing its terminal.

The default API is `http://127.0.0.1:8000`. View its status at `/health`. By default, managed files are under `local-data/`. To check a downloaded file, run:

```powershell
ffprobe -v error -show_entries stream=codec_name,width,height,display_aspect_ratio,duration -of json "clip-01.mp4"
```

The CLI also supports local inspection and basic rendering:

```powershell
.\.venv\Scripts\python.exe -m autoclip inspect "recording.mkv"
.\.venv\Scripts\python.exe -m autoclip clip "recording.mkv" --count 2 --length 20 --aspect-ratio 9:16 --resolution 480
```

## Troubleshooting and limitations

| Symptom | What to check |
| --- | --- |
| The dashboard cannot reach the processor | Check both terminals, use the documented localhost ports, and run the health command above. |
| No candidates appear | Quiet or steady audio can produce zero candidates. Try speech ranking with a prepared model or choose a manual interval. |
| Captions are missing or unreadable | Confirm the selected model is prepared, the clip contains overlapping speech, and Windows has a suitable font. Language detection and recognition can make mistakes. |
| Framing falls back or fails | Auto preserves more of the frame when evidence is weak. Select a smaller manual region or use Full Frame. Smart framing currently needs unrotated, square-pixel input. |
| Import fails or a job takes longer than expected | Finish the OBS recording, check free space and codec support, and start with a short clip at 480p or 720p. Model inference may take time to acknowledge cancellation. |
| A project reports incomplete deletion | Stop its jobs, close players holding project files open, and retry cleanup. Keep original recordings in a separate folder. |

Automatic focus uses sampled motion, scene changes, and lightweight face detection. It can miss gameplay subjects, webcams, or HUD elements. Interactive validation and fresh-machine setup status are tracked in the [release-readiness report](RELEASE_READINESS.md).

See [CONTRIBUTING.md](CONTRIBUTING.md) for development and testing, [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for upstream dependencies, and [CHANGELOG.md](CHANGELOG.md) for changes. A project license is pending owner approval.
