# Smart reframing

This extends the existing selection, single-worker queue and FFmpeg export pipeline.
It runs locally on CPU. Visual evidence is heuristic; motion does not establish
semantic importance, and a face detector can mistake an in-game face for a person.
Review every exported clip before using it.

## Setup and use

Install the optional visual dependencies in the existing environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-vision.txt
```

The pinned OpenCV headless wheel includes the local Haar cascade. Keep its bundled
license notices when redistributing; no model is downloaded during analysis.
Existing FFmpeg, backend and speech requirements still apply. On a fresh machine,
install those requirements and prepare the speech model before going offline.
Build the frontend after source changes, then restart both loopback services.
Installation and machine migration remain subject to the user's authorization.

In the dashboard's framing controls:

- **Hybrid Focus** is the default for new dashboard workspaces. It keeps a wider
  source region than Focus Crop and fills any unused canvas with blur or padding.
- **Focus Crop** enlarges a selected source region to fill the canvas. Set a point or
  disable Auto Focus for a fixed crop. Weak automatic evidence can use Hybrid Focus.
- **Auto** chooses a crop only with persistent evidence and preserves the entire
  source when confidence is low. Older saved Smart Tracking Crop remains supported.
- **Streamer + gameplay** fits the webcam above the entire gameplay frame. Automatic
  webcam proposals require a stable corner face and boundary evidence. Select the
  webcam region manually when detection is uncertain. Split supports all four shapes.
- **Full Frame** fits the whole source over a blurred or padded background.
- **Legacy layout** retains the original fit/center-crop rendering path.

Load a source frame after importing a recording. Click a focus point or drag a focus
or webcam region; numeric coordinates use the normalized range 0–1. Manual focus
is fixed and takes priority over automatic tracking. A focus region constrains the
tracker and can trigger a wider composition or Full Frame if the crop cannot retain it.
Use the position sliders, foreground zoom, Lock Position, or Reset to refine the crop.
The instant overlay is a drafting guide. Request a composition preview for a still
rendered by the same planner and FFmpeg composition as export. The still shows caption
guides. Final playback includes actual burned-in captions when available. Preview
extraction shares the single worker and can wait behind a render.

Adjust tracking intensity, caption position and social-interface safe margins.
Optional emphasis uses at most three small zoom pulses, separated by eight seconds,
only when reliable subject evidence and activity agree. It is disabled by default.
Caption Auto uses a split seam or lower background area where appropriate. This is
layout-aware placement, not pixel-level text/HUD collision detection. Fonts must be
installed locally for the spoken/written language; transcription quality varies.
Long caption text is divided into at most two visible lines per timed ASS event.

Open **Adjust clip** to change framing and render a revision. The original remains.
Framing revisions of speech-enabled jobs reuse the validated parent transcript and
explicit interval; inference and highlight selection do not run again. Missing or
invalid parent transcripts produce an actionable failure instead of silent inference.
Visual evidence is cached by source identity, interval, geometry and analyzer version;
layout/intensity changes can reuse it. Changed intervals need new visual analysis.

## Implementation map

| Module | Responsibility |
| --- | --- |
| `autoclip/reframing.py` | Validated settings, normalized regions, even crop geometry, immutable plans |
| `autoclip/vision.py` | `analyze_candidate`, `analyze_frames`, `plan_from_analysis`, `smooth_track`; sampled evidence and cache |
| `autoclip/composition.py` | `build_filtergraph`; cosine-eased pan, scene cuts, fit/blur/split, optional subtle emphasis |
| `autoclip/engine.py` | `process` inserts visual planning after selection; `render_clip` composes then captions with existing audio mapping |
| `autoclip/speech.py` | `validate_saved_transcript`, `write_subtitles`; trusted identity checks and caption safe zones |
| `autoclip/service.py` | `revision_transcript`, `frame_preview`, `execute`; managed files and one worker |
| `autoclip/api.py` | Strict framing request models, revision inheritance, queued frame and safe JPEG routes |
| `web/components/FramingEditor.tsx` | Controls, source selection and composition guide |
| `web/lib/framing.ts` | Coordinate conversion, validation and preview geometry |

Detailed analysis decodes only selected 15–60-second intervals at 3 FPS, maximum
640 pixels on either edge. Only metadata survives temporary frame decoding. Plans retain at
most 64 keyframes. OpenCV and filter graph threads are bounded; x264 uses the existing
configured CPU thread count. There is no GPU requirement, cloud inference or API bill.
Manual/fitted rendering remains available if OpenCV is absent. A missing automatic
analyzer produces a recorded preserving fallback.

The current framed renderer requires unrotated square-pixel input. Normalize unusual
source orientation/pixel aspect before using framing; unsupported geometry fails
clearly. Tiny or overly wide target regions preserve content. Face and webcam scores
are rule-based confidence values, not calibrated probabilities.

## Reproducible verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

In `web/`: `npm.cmd test`, `npm.cmd run typecheck`, `npm.cmd run build`.
Actual FFmpeg tests check all compositions, moving crops, emphasis, caption burn-in,
dimensions, stream decoding, A/V timestamps and cancellation. Worker tests prove
framing revisions reuse the transcript without calling inference or selection.

For an authorized source directory with three recordings containing seconds 5–20:

```powershell
.\.venv\Scripts\python.exe -m tools.compare_reframing "C:\path\to\recordings"
```

This writes comparison MP4s, sampled JPEGs and timing/stream metadata under ignored
`local-data/reframing-acceptance`. Each invocation creates a fresh run subdirectory; analysis metadata can be cached
across runs. Existing files from another source are never reused as comparison output. Original sources are not
modified. The first source also gets a manual split-region demonstration; it does
not assert that the selected region is a webcam. Caption demo text is labeled and
does not claim to transcribe the source. No source paths or transcript contents go
into the report. Timings describe observed local runs, not guaranteed throughput.

Manual acceptance: run a recording with known subjects/HUD and a real webcam. Compare
legacy center crop, Auto, smart crop, manual focus, split and full gameplay. Check
both portrait and landscape (split portrait only), pan jitter across cuts, HUD/subject
retention, captions, safe margins, playback/lip synchronization and download. Change
framing on a speech-enabled clip, verify `saved_job` transcript reuse, then refresh to
check persistence. Cancel a queued preview/render. Interactive browser acceptance,
real webcam quality, human event judgments and desktop measurements remain separate
from automated and sampled-image checks.
