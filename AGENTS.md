# Clipper0 — Mandatory Agent Operating Rules

> **READ THIS FIRST.** Applies to every AI coding agent working in this repository, whether invoked from VS Code, terminal, or another editor.

---

## 0. Smart Autonomy Policy

This policy replaces the previous per-action confirmation gate. Agents are expected to work efficiently without interrupting development for every small edit.

### 0.1 Actions that do NOT require permission

You are authorized to perform the following routine development tasks inside the Clipper0 project workspace without requesting confirmation:

- Reading, searching, and inspecting project files.
- Analyzing source code and dependencies.
- Creating and modifying ordinary project source files (code, tests, documentation, configuration).
- Fixing bugs and making small refactors within the approved feature scope.
- Running short local commands (compilation checks, linting, formatting, type checks).
- Running lightweight unit and integration tests.
- Inspecting Git status and local diffs (read-only).
- Making non-destructive configuration adjustments.
- Maintaining `progress.md` and implementation notes.
- Updating documentation and changelogs.

Work efficiently. Report completed changes, affected files, and results when a meaningful chunk of work is done.

### 0.2 Actions that REQUIRE explicit permission

#### A. Browser access

Ask before:

- Opening or navigating websites using browser automation.
- Accessing online accounts.
- Performing browser-based downloads or uploads.
- Interacting with external websites or online services.
- Submitting forms or performing actions through a browser.

Explain which website you intend to access and why before asking.

#### B. Major or long-running operations

Ask before operations that may require the computer to remain awake for an extended period. Examples:

- Processing or transcribing a 2–3-hour recording.
- Running full video-analysis pipelines on real source files.
- Performing lengthy FFmpeg rendering or batch exports.
- Downloading large AI models or datasets.
- Running resource-intensive benchmarks.
- Executing long integration or end-to-end test suites.
- Running sustained CPU-intensive workloads.
- Starting long-running background services or processing jobs.

Before requesting approval, describe:
1. The exact operation.
2. Why it is necessary.
3. Which resources it will use.
4. The estimated resource demands, if known.
5. Whether the computer must stay awake.
6. How the operation can be stopped safely.

Wait for explicit approval before starting.

#### C. Destructive or external actions

Do not perform these without explicit permission:

- Deleting source files, recordings, or project data outside routine temporary-file cleanup.
- Overwriting significant user work.
- Resetting Git history or force-pushing.
- Publishing code or making repositories public.
- Uploading private files or sharing secrets.
- Changing system-wide settings.
- Installing system-level software requiring administrator privileges.
- Running unknown or untrusted scripts.

These require permission even if they are quick.

### 0.3 Development workflow

1. Inspect the relevant Clipper0 code.
2. Identify the problem and intended change.
3. Implement routine, non-destructive improvements autonomously.
4. Run lightweight verification.
5. Report completed changes, affected files, and test results.
6. Update `progress.md` when appropriate.
7. Ask permission only when a restricted action (§0.2) is necessary.

Do not interrupt development for every small edit. Do not request blanket permissions for restricted operations. If an action is ambiguous, explain the risk and ask before proceeding.

### 0.4 Long-running task notifications

For any approved long-running operation:

- Explain that the PC/laptop should remain awake.
- Show meaningful progress where technically possible.
- Avoid redundant processing.
- Save checkpoints or intermediate results when supported.
- Handle cancellation safely.
- Report failures clearly.
- Do not automatically repeat a failed expensive operation without reviewing the cause.

Do not change Windows sleep settings without separate permission.

---

## 1. Primary objective

Build a fully local, free-to-run, CPU-friendly AI video highlight clipping application. Record input with OBS or import owned/authorized MP4/MKV, identify **candidate** highlights, generate vertical subtitled clips, review/adjust/download from a localhost web dashboard. No paid AI API and no mandatory GPU. Prioritize correctness and measured quality over claims of 'viral' prediction.

## 2. Environment and sequence

- **Develop and test on user's laptop first. Laptop specifications are UNKNOWN.** Ask for laptop OS, CPU, RAM, free storage, and whether FFmpeg/Python/Node/Git are installed before choosing model size or concurrency. Do not assume laptop = desktop.
- Then transfer project with GitHub to user's **desktop**: Windows 10, AMD Ryzen 5 5600G, 16 GB RAM, no discrete GPU, >20 GB free SSD, 1 TB HDD, OBS Studio.
- Do not store videos, audio, transcript personal data, database files, model weights, secrets, or virtual environments in Git. Provide a repeatable installation and migration checklist.

## 3. Communication and workflow

- Read `progress.md` before starting work and maintain it as the agent handoff report. Record the start and finish of every feature, operation, or coherent work chunk. At the start, record scope, intended files, and verification plan. At the finish, record actual changes, outcomes, checks, unresolved work, and the next step. Record failures, interruptions, and blockers at the exact stopping point. Keep the current handoff and active work sections accurate. Treat reporting edits as part of their associated chunk.
- Work on **one small milestone** at a time.
- Explain significant changes in plain English. Include code snippets/diffs when helpful.
- Keep a changelog of completed work.
- Every implemented feature needs a reproducible manual test and, where practical, an automated test.
- Use free, local, officially maintained tools where practical. Verify versions and platform support before installing. Never promise precise clip accuracy or processing speed without measurement.
- If you discover missing info or a blocker, explain options and ask; do not invent results.

## 4. Security and legal boundaries

- Work with recordings the user owns or has permission to process. Do not bypass DRM, paywalls, account access, or platform restrictions.
- Bind web/backend servers to 127.0.0.1 by default. Validate uploads, duration, size, extensions, media streams, and path access. Never pass untrusted file paths directly into shell commands.
- Use subprocess argument arrays (not shell=True) to invoke FFmpeg; sanitize export names and avoid directory traversal.
- Never commit secrets, API tokens, local paths, identifiable metadata, or recordings. Respect software/model licenses; check before redistribution.
- Publishing integrations, remote access, and livestream capture require a separate approved phase.

## 5. Source of truth and reading order

1. `AGENTS.md` — mandatory agent conduct and autonomy policy
2. `progress.md` — current state, prerequisites, active work, verification, and agent handoff
3. `PROJECT_BRIEF.md` — requirements and scope
4. `ARCHITECTURE.md` — boundaries, interfaces and data model
5. `IMPLEMENTATION_PLAN.md` — staged milestones
6. `TESTING_AND_ACCEPTANCE.md` — what 'works' means
7. `SETUP_LAPTOP.md` — laptop-first setup
8. `GITHUB_MIGRATION.md` — desktop transfer procedure
9. `COST_AND_PERFORMANCE.md` — zero API charge, real-world tradeoffs
10. `PROMPTS_FOR_AGENT.md` — suggested starting prompts
11. `.github/copilot-instructions.md` — editor-specific reinforcement

## 6. Definition of done for MVP

A 10-minute user-supplied OBS recording can be imported and processed **offline** into up to three candidate 15–60s vertical clips with captions where speech exists; clips play in a local browser and can be downloaded. Application survives empty speech, noisy audio, long files, cancelled jobs, processing failures and missing binaries gracefully. Actual throughput/quality recorded on the laptop before migration.
