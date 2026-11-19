# GitHub Transfer — Laptop to Desktop

## Policy
Each command or edit requires one separate clear user confirmation under `AGENTS.md`. Never auto-push, auto-pull or make a public repository without approval.

## Preparation on laptop
1. Review Git diff and `.gitignore` for sensitive/large files; request approval for inspection commands.
2. Ensure recordings, subtitles containing identifiable speech, generated clips, caches, SQLite databases, local `.env*`, virtual environments, model weights and tokens are excluded.
3. Write `README.md`, pinned Python dependencies/lockfile where possible, `package-lock.json`, `.env.example` and test instructions. Each file action separately approved.
4. Decide **private GitHub repository** by default; confirm repository ownership and destination with user.
5. Confirm that no sensitive file was previously committed; `.gitignore` does not erase history.
6. Request explicit approval for each init, add, commit, remote, push action.

## Example commands (NOT automatically executable)
```powershell
git status
git diff --stat
git add AGENTS.md PROJECT_BRIEF.md
git commit -m "docs: add development instructions"
git push -u origin main
```
These are examples only; actual paths/branch/remotes must be inspected first. **Do not run as a batch.**

## Windows 10 desktop environment
- AMD Ryzen 5 5600G, 16GB RAM, integrated graphics; no NVIDIA/CUDA assumption.
- >20GB available SSD, 1 TB HDD; HDD drive letter unknown.
- Configure source/virtual environment and lightweight models on SSD (as space permits); recordings and outputs on HDD.
- OBS sample media remains outside Git; transfer by local USB/network separately if required, with user's consent.
- Verify Node/Python/FFmpeg compatibility with Windows 10 and each dependency before installing.
- Clone approved private repository; recreate Python venv; install pinned dependencies; download model cache; configure local paths; execute health check and acceptance tests with approvals.

## Environment portability
- No absolute paths in code; use `pathlib` in Python, environment variables and path validation.
- `.env.example` placeholder names: `AUTOCLIP_DATA_DIR`, `AUTOCLIP_MODEL_CACHE_DIR`, `AUTOCLIP_DB_PATH`, `AUTOCLIP_FFMPEG_PATH`, `AUTOCLIP_FFPROBE_PATH`, `AUTOCLIP_WORKER_THREADS`, `AUTOCLIP_MODEL_SIZE`.
- Use git attributes for consistent line endings as needed. Don't commit machine-specific settings.

## Migration acceptance
- Clean clone builds/starts without secrets or video files from laptop.
- Same 10m OBS fixture (copied explicitly outside Git) yields playable clips on desktop.
- Record speed/RAM comparison and any Windows-specific fixes.

## Reframing migration

Include requirements-vision.txt and SMART_REFRAMING.md with source code; install the visual dependency on the destination machine and retain bundled license notices. Keep all local-data/reframing caches, preview JPEGs and acceptance recordings/results out of Git. Repeat real webcam/browser and performance acceptance on Windows 10 before claiming desktop verification.
