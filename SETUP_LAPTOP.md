# Laptop setup

Follow the [Windows installation and startup guide](README.md#install-on-windows) for the tested Python, Node.js, and FFmpeg setup. [Release verification](RELEASE_READINESS.md) records which environments and workflows were checked.

To check your laptop before installing dependencies, run these PowerShell commands.

```powershell
py -0p
node --version
npm.cmd --version
git --version
ffmpeg -version
ffprobe -version
```

Keep original OBS recordings outside managed output folders. Use [.env.example](.env.example) to identify optional environment overrides. The app copies imports, writes a SQLite job database, and can cache local models and analysis results, so reserve room on the drive that contains the app data directory.

[AGENTS.md](AGENTS.md) governs agent permissions. [GITHUB_MIGRATION.md](GITHUB_MIGRATION.md) describes moving the source and recreating the local environment on a second computer.
