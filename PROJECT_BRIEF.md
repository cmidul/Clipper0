# Project Brief — Clipper0

## Problem
Editors manually review long gameplay recordings to find meaningful reactions or highlights, cut vertical clips, and caption them. We want to reduce that manual effort on affordable hardware with no paid inference service.

## Audience and operating conditions
Individual creator using OBS; all processing local, first on a laptop of **unknown specs**, eventually on a Windows 10 desktop (Ryzen 5 5600G, 16 GB RAM, iGPU, 20+ GB SSD free, 1 TB HDD). This is an offline-first single-user desktop-hosted web app, **not** a public SaaS MVP.

## Core user journey
1. Record with OBS (prefer MKV for capture reliability) or import an MP4/MKV the user is authorized to process.
2. See file details (duration, codec, size) and configure clip count (default up to 3), length (15–60s), and output resolution.
3. Start one background processing job; see progress, step names, and errors.
4. Pipeline finds candidate moments and explains score signals (audio peak, speech event, transcript cue, scene change).
5. Produce vertical MP4 clips with readable burned-in subtitles when speech is present.
6. Preview, revise start/end timestamps, regenerate an individual clip, and download.

## Functional requirements
- Local import; predictable storage/output paths; no paid APIs or login required on localhost.
- FFprobe metadata extraction; FFmpeg processing; CPU-friendly speech recognition and segmentation.
- Candidate windows from audio event features, speech/transcript cues, optional scene changes; overlap removal and minimum spacing.
- Stable scoring with documented normalization and configurable weights; **do not promise viral prediction**.
- Text transcript with timestamps, subtitles (.srt/.ass), original and output links, job progress, errors.
- Optional subtitles for speechless moments; silence must not fail job.
- Review interface with clear status: proposed vs approved clips.

## Non-goals for MVP
- Direct YouTube/Twitch/Facebook scraping or DRM circumvention; cross-platform auto-posting; live multi-stream real-time analysis; commercial multi-user hosting; end-to-end contextual gaming event recognition; accurate facial tracking; guaranteed virality.

## Constraints
- Zero mandatory AI API calls and zero API tokens per processed video.
- Windows-compatible; Python AI worker plus TypeScript UI.
- Laptop-first testing; evaluate speed and memory before locking concurrency and AI model.
- 1 video processing job at a time at first.
- User approvals required before **every** action: see `AGENTS.md`.

## Quality bar
Correct timestamps, no clip outside video bounds, no arbitrary 16:9 stretch, synced captions, reasonable failure messages. For vertical conversion start with center crop or padded layout and let user choose; intelligent subject tracking is later work.
