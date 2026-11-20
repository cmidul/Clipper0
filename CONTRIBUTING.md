# Contributing to Clipper0

Open a GitHub issue or propose a focused patch. Include the OS, tool versions, exact reproduction steps, and the expected and observed behavior. Use a synthetic fixture or a recording you are allowed to share. Remove account names, local paths, credentials, transcripts, and user video from logs and attachments.

Follow the [setup guide](README.md#install-on-windows) and the repository's [AGENTS.md](AGENTS.md). From the project root, run the targeted tests for your change. Test the corresponding dashboard or CLI workflow with disposable data.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_reframing.py
Set-Location web
npm.cmd test
npm.cmd run typecheck
```

Real render tests need FFmpeg and FFprobe. Speech integration uses a prepared local model and a supported Windows speech voice or its documented fixture. Keep tests offline after setup and use temporary project directories. Document changed behavior and include reproducible checks with your patch.

For a suspected security vulnerability, use a private reporting channel if the repository owner has enabled one. Avoid posting secrets or private media in public issues. New contributions intended for open-source distribution should wait for the owner to select and publish the project license.
