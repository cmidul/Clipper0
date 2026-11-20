export type ProjectAssetStatus = "available" | "deleting" | "deleted" | "deletion_incomplete";

export type Media = {
  id: string;
  filename: string;
  duration: number;
  width: number;
  height: number;
  codec: string;
  audio_present: boolean;
  size_bytes: number;
  created_at: string;
  archived_at: string | null;
  asset_status: ProjectAssetStatus;
};

export type AssetDeletionResult = {
  media: Media;
  failures: { asset: string; reason: string }[];
};

export const ASPECT_RATIO_OPTIONS = [
  { value: "9:16", label: "9:16 (Vertical)" },
  { value: "16:9", label: "16:9 (Horizontal)" },
  { value: "1:1", label: "1:1 (Square)" },
  { value: "4:5", label: "4:5 (Portrait)" },
] as const;
export const VIDEO_QUALITY_OPTIONS = [
  { value: 1080, label: "1080p — Full HD" },
  { value: 720, label: "720p — HD" },
  { value: 480, label: "480p — SD" },
] as const;
export const COMPRESSION_OPTIONS = [
  { value: "higher_quality", label: "Higher Quality" },
  { value: "balanced", label: "Balanced" },
  { value: "smaller_file", label: "Smaller File" },
] as const;

export type AspectRatio = typeof ASPECT_RATIO_OPTIONS[number]["value"];
export type Resolution = typeof VIDEO_QUALITY_OPTIONS[number]["value"];
export type Compression = typeof COMPRESSION_OPTIONS[number]["value"];
export type FocusPoint = { x: number; y: number };
export type FocusRegion = FocusPoint & { width: number; height: number };
export type FramingMode = "auto" | "focus_crop" | "hybrid_focus" | "full_gameplay" | "streamer_gameplay" | "smart_crop";
export type FramingOptions = {
  mode: FramingMode;
  focus_point?: FocusPoint | null;
  focus_region?: FocusRegion | null;
  webcam_region?: FocusRegion | null;
  background?: "blur" | "pad";
  tracking_intensity?: number;
  subtitle_position?: "auto" | "top" | "center" | "bottom";
  safe_margin_horizontal?: number;
  safe_margin_top?: number;
  safe_margin_bottom?: number;
  emphasis_zoom?: boolean;
  foreground_zoom?: number;
  auto_focus?: boolean;
  smooth_tracking?: boolean;
  lock_position?: boolean;
};
export const DEFAULT_FRAMING: FramingOptions = {
  mode: "hybrid_focus", background: "blur", tracking_intensity: 0.5, subtitle_position: "auto",
  foreground_zoom: 1, auto_focus: true, smooth_tracking: true, lock_position: false,
};
export const FRAMING_LABELS: Record<FramingMode, string> = {
  focus_crop: "Focus Crop", hybrid_focus: "Hybrid Focus", full_gameplay: "Full Frame",
  auto: "Auto", streamer_gameplay: "Streamer + gameplay", smart_crop: "Smart tracking crop (legacy)",
};
export type FramingPlan = {
  start: number; end: number; source_width: number; source_height: number;
  selected_mode: FramingMode; confidence: number; fallback_reason: string | null;
  keyframes: { time: number; scene_id: number; crop: { x: number; y: number; width: number; height: number } }[];
};

export function aspectRatioParts(aspectRatio: AspectRatio): [number, number] {
  const [width, height] = aspectRatio.split(":").map(Number);
  return [width, height];
}

export function outputDimensions(resolution: Resolution, aspectRatio: AspectRatio): { width: number; height: number } {
  const [ratioWidth, ratioHeight] = aspectRatioParts(aspectRatio);
  const longSide = 2 * Math.ceil(resolution * Math.max(ratioWidth, ratioHeight) / (2 * Math.min(ratioWidth, ratioHeight)));
  return ratioWidth <= ratioHeight ? { width: resolution, height: longSide } : { width: longSide, height: resolution };
}

export function outputSizeLabel(resolution: Resolution, aspectRatio: AspectRatio): string {
  const { width, height } = outputDimensions(resolution, aspectRatio);
  return `${width} × ${height}`;
}

export type JobState = "queued" | "running" | "completed" | "failed" | "cancelled";
export type Job = {
  id: string;
  media_id: string;
  source_candidate_id: string | null;
  state: JobState;
  phase: string;
  progress_pct: number;
  cancel_requested: boolean;
  error_message: string | null;
  diagnostic: string | null;
  caption_status: string | null;
  language: string | null;
  transcript_cache_hit: boolean | null;
  transcript_reuse_kind?: string | null;
  kind?: "render" | "frame_preview";
  frame_url?: string | null;
  frame_framing_mode?: FramingMode | null;
  elapsed_seconds: number | null;
  created_at: string;
  options: {
    layout: "pad" | "crop";
    aspect_ratio?: AspectRatio;
    resolution?: Resolution;
    compression?: Compression;
    framing?: FramingOptions | null;
  };
};

export type ReviewState = "proposed" | "approved" | "rejected";
export type Candidate = {
  id: string;
  job_id: string;
  source_candidate_id: string | null;
  start: number;
  end: number;
  score: number;
  review_state: ReviewState;
  clip_id: string;
  preview_url: string;
  download_url: string;
  has_subtitles: boolean;
  framing?: FramingPlan | null;
  effective_framing?: FramingOptions | null;
  visual_analysis?: { cache_hit: boolean; scene_count?: number; error?: string } | null;
  evidence: {
    contributions?: Record<string, number>;
    cue_matches?: string[];
    score_kind?: string;
  };
};

export function localApiBase(value: string): string {
  const url = new URL(value);
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(url.hostname)
      || url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("The processor URL must be a localhost HTTP address.");
  }
  return url.origin;
}

const API = localApiBase(process.env.NEXT_PUBLIC_AUTOCLIP_API_URL || "http://127.0.0.1:8000");

export function apiPath(path: string): string {
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new Error("Expected a local API route.");
  }
  return `${API}${path}`;
}

export function processorErrorMessage(message: string): string {
  const failedTool = /^(ffmpeg|ffprobe)(?:\.exe)? failed\./i.exec(message)?.[1].toLowerCase();
  if (failedTool === "ffmpeg") return "FFmpeg could not process this recording. Retry or try another recording.";
  if (failedTool === "ffprobe") return "FFprobe could not read this recording. Check that the file plays and try importing it again.";
  return message;
}

export function errorDetail(payload: unknown, status: number): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = payload.detail;
    if (typeof detail === "string") return processorErrorMessage(detail);
    if (Array.isArray(detail)) {
      return detail.map((item) => typeof item?.msg === "string" ? item.msg : "Invalid field").join(" · ");
    }
  }
  return `The processor returned an error (${status}).`;
}

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiPath(path), {
      ...options,
      headers: { ...(typeof options.body === "string" ? { "Content-Type": "application/json" } : {}), ...options.headers },
      cache: "no-store",
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new Error("Cannot reach the local processor. Start the Python API, then retry.");
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(errorDetail(payload, response.status));
  return payload as T;
}

export async function requestPreviewFrame(mediaId: string, body: object, signal: AbortSignal): Promise<Job & { frame_url: string }> {
  let job = await apiRequest<Job>(`/media/${mediaId}/frames`, { method: "POST", body: JSON.stringify(body), signal });
  for (let attempt = 0; attempt < 600 && job.state !== "completed"; attempt++) {
    if (job.state === "failed") throw new Error(job.error_message ? processorErrorMessage(job.error_message) : "Frame preview failed. Try again.");
    if (job.state === "cancelled") throw new Error("Frame preview cancelled.");
    await new Promise<void>((resolve, reject) => {
      const abort = () => { clearTimeout(timer); reject(new DOMException("Cancelled", "AbortError")); };
      const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, 500);
      if (signal.aborted) abort();
      else signal.addEventListener("abort", abort, { once: true });
    });
    job = await apiRequest<Job>(`/jobs/${job.id}`, { signal });
  }
  if (!job.frame_url) throw new Error("Preview is still queued. Retry after current processing finishes.");
  return { ...job, frame_url: job.frame_url };
}

export function uploadFile(file: File, progress: (value: number) => void, signal: AbortSignal): Promise<Media> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    const abort = () => request.abort();
    const cleanup = () => signal.removeEventListener("abort", abort);
    request.open("POST", apiPath(`/media/import?filename=${encodeURIComponent(file.name)}`));
    request.setRequestHeader("Content-Type", "application/octet-stream");
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) progress(Math.round(event.loaded / event.total * 100));
    };
    request.onload = () => {
      cleanup();
      let payload: unknown;
      try { payload = JSON.parse(request.responseText); } catch { payload = null; }
      if (request.status >= 200 && request.status < 300) resolve(payload as Media);
      else reject(new Error(errorDetail(payload, request.status)));
    };
    request.onerror = () => { cleanup(); reject(new Error("Upload failed. Check that the local processor is running.")); };
    request.onabort = () => { cleanup(); reject(new DOMException("Upload cancelled.", "AbortError")); };
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) { cleanup(); reject(new DOMException("Upload cancelled.", "AbortError")); return; }
    request.send(file);
  });
}

export function formatTime(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor(whole / 60) % 60;
  const remainder = String(whole % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${remainder}` : `${minutes}:${remainder}`;
}

export function formatSize(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${Math.max(0.1, bytes / 1024 ** 2).toFixed(1)} MB`;
}

export function intervalError(start: number, end: number, duration?: number): string | null {
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0) return "Enter valid start and end times in seconds.";
  if (end - start < 15 || end - start > 60) return "Clips must be between 15 and 60 seconds long.";
  if (duration !== undefined && end > duration) return `The end time must stay within the ${formatTime(duration)} recording.`;
  return null;
}

export function isActive(job: Job): boolean {
  return job.state === "queued" || job.state === "running";
}
