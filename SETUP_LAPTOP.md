# Laptop-First Setup Guide

**Do not execute these example commands without separate user confirmation for EACH command.** This is a checklist, not an instruction to run unattended.

## Step 0 — ask, don't assume
Laptop CPU/model, operating system/version, RAM, disk free space, dedicated GPU (if any), sample video language, drive letters, OBS output. Then select appropriate tools.

## Tools and official sources
- Git: https://git-scm.com/downloads
- VS Code: https://code.visualstudio.com/
- Python: https://www.python.org/downloads/ (project target 3.11 64-bit if supported on laptop)
- Node.js: https://nodejs.org/en/download (supported LTS compatible with installed OS and selected Next.js release)
- FFmpeg: https://ffmpeg.org/download.html (Windows users need an actual Windows binary build)
- OBS: https://obsproject.com/

## Reference preflight commands (propose individually)
Windows PowerShell:
```powershell
python --version
py -3.11 --version
node --version
npm --version
git --version
ffmpeg -version
ffprobe -version
```
Linux/macOS equivalents may differ. Before any installation, check officially supported versions, disk footprint and Python wheel compatibility.

## Suggested paths (configure per machine)
```text
<project-root>/       # git-controlled source and examples
<local-data-dir>/     # user-owned videos and generated output, NOT Git
    recordings/
    imports/
    audio-cache/
    transcripts/
    clips/
    temporary/
    models/
```
Use `.env.example` with placeholders for paths; local `.env.local` and data folder are ignored.

## Python installation sketch (commands require separate approval)
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r worker
equirements.txt
```
Exact requirements must be pinned/tested with laptop platform. Avoid installing CUDA/PyTorch GPU wheels without need. Some Silero setups depend on torch or onnxruntime: confirm exact dependency tree and wheel availability first.

## Web frontend sketch (commands require separate approval)
```powershell
node --version
npm --version
npm ci
```
`npm ci` only after `package-lock.json` exists and has been reviewed. No automatic install unless approved.

## Model preparation
When authorized, download multilingual `base` Faster-Whisper model once and cache locally. Model downloads need internet initially; inference thereafter can be offline. Prefer a configured cache directory outside Git. Check the model's license before publishing/distributing it.

## Run order (after code exists and each command is separately authorized)
1. Python backend health/preflight.
2. Minimal CLI video render.
3. Speech/subtitle pipeline.
4. Local backend and frontend.
5. Laptop acceptance tests.

## Laptop constraints
Use one job at a time and avoid heavy models until measured. If laptop has 8GB RAM or weaker CPU, use `tiny` or `base`, lower analysis frame rate and fewer threads. The Ryzen desktop baseline does not automatically apply to laptop.

## Optional Smart Reframing dependency

Install requirements-vision.txt in the existing virtual environment after authorizing setup; it pins CPU-only OpenCV headless and the compatible NumPy version. No additional face model download is required. See SMART_REFRAMING.md for setup and limits; rebuild the existing dashboard and restart services after changes.
