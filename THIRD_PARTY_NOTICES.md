# Third-party dependencies and assets

Clipper0 is intended to ship as source with dependency manifests. Its installation downloads dependencies separately. This inventory is based on installed package metadata, bundled license files, and local model provenance. It is a dependency review for the source release. Bundling executables, wheels, fonts, or model weights would require a separate redistribution review.

| Component | License evidence checked locally |
| --- | --- |
| FastAPI and Pydantic | MIT, installed wheel license files |
| Starlette and Uvicorn | BSD-3-Clause, installed wheel license files |
| Faster-Whisper, CTranslate2, and ONNX Runtime | MIT, installed package metadata |
| PyAV and NumPy | BSD-3-Clause for the main projects. Wheels contain or use components with their own notices. |
| OpenCV headless | Apache-2.0 package with bundled third-party notices. The frontal-face cascade includes an Intel redistribution and attribution notice in its XML header. |
| Hugging Face Hub and Tokenizers | Apache-2.0, installed package metadata |
| Next.js, React, and React DOM | MIT, installed package manifests |
| Inter Variable font | SIL Open Font License 1.1, installed font package. Preserve the included notice when distributing built frontend assets with the font. |
| FFmpeg and FFprobe | The local build reports GPL v3 or later and includes x264. Users obtain compatible tools separately. The repo ships no FFmpeg executable. |
| Systran converted multilingual Faster-Whisper model | Local provenance records MIT and a concrete snapshot revision. Verify the upstream model card and notices before redistributing weights. |

Include existing upstream notices when redistributing a dependency or asset. The repository uses local artifacts for speech models and the optional OpenCV cascade, with no downloaded weight files tracked. [Dependency manifests](README.md#install-on-windows) pin the environment. The repository's own license is a separate owner decision.

An up-to-date upstream dependency advisory review and independent model-card review are pending.
