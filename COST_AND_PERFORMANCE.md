# Cost, Performance and Reality Checks

## Cost model
Required external AI inference API calls: **0**. Required tokens processed by paid services: **0**. Local model inference consumes CPU cycles, RAM, electricity and time, not provider tokens. Localhost requires no paid hosting. Initial installer/model downloads need internet; cloud hosting or optional future public publishing can incur costs.

## Desktop target
Ryzen 5 5600G (6C/12T), 16GB RAM, Windows 10, no discrete GPU, 20+GB SSD free, 1TB HDD. Initial defaults: 1 job, Faster-Whisper multilingual `base`, `int8`, CPU threads ~6, beam size 1, analysis downsampled; final settings based on profiling.

## Laptop target
UNKNOWN. Don't assert how fast it can transcribe or render. Gather specs and benchmark a 60s and 10m recording. Start with conservative settings, e.g. one job and 2–4 threads; adapt afterward.

## Bottlenecks
- Transcription: CPU-bound, model size and speech density matter.
- Video rendering: H.264 CPU encoding can be slow; use modest resolution/preset.
- Scene detection: process sparse/downscaled frames.
- HDD I/O: big recordings are fine on HDD; keep temporary small files on fastest suitable drive if enough capacity.
- Concurrent OBS recording and analysis: can overload laptop or 5600G; defer live processing.

## Tradeoffs and fallbacks
- Faster results: `tiny`/`base`, `beam_size=1`, skip word timing, use audio-first filtering, process low-res frames.
- Better speech accuracy: try `small` model, with CPU time/RAM tradeoff measured; multilingual `base` may struggle with noisy gaming and Bangla code-switching.
- Highlight quality: transparent rules can be useful but cannot understand all gaming context. Human review remains necessary.
- Captions: segments are coarse; word-level captions can be an optional slower mode.
- Vertical layouts: offer letterbox/blur-pad as safe default; center crop can remove HUD/subject.

## What to measure
Wall-clock analysis/render time, real-time factor (processing seconds / recording seconds), peak RAM, CPU usage, clip count, false highlights, missed highlights, transcription quality, subtitle sync.

## Don't make these claims
- 'Perfect' highlight selection or reliable viral prediction.
- Guaranteed real-time monitoring on CPU.
- Free electricity, storage and bandwidth.
- Native auto-posting to every social platform without approvals/API checks.
