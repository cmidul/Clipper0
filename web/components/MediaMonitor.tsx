"use client";

import { useEffect, useRef, useState, type CSSProperties, type FormEvent } from "react";
import { apiPath, formatTime, requestPreviewFrame, type Media } from "../lib/api";

function mediaAspect(ratio?: number) {
  return ratio ? { "--media-ratio": ratio } as CSSProperties : undefined;
}

export function VideoMonitor({ src, label, ratio, local = false }: {
  src: string;
  label: string;
  ratio?: number;
  local?: boolean;
}) {
  const [intrinsicRatio, setIntrinsicRatio] = useState<number>();
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [controlError, setControlError] = useState<string>();
  const monitor = useRef<HTMLDivElement>(null);
  const player = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const updateFullscreen = () => setFullscreen(document.fullscreenElement === monitor.current);
    document.addEventListener("fullscreenchange", updateFullscreen);
    return () => document.removeEventListener("fullscreenchange", updateFullscreen);
  }, []);

  async function togglePlayback() {
    const video = player.current;
    if (!video) return;
    setControlError(undefined);
    if (!video.paused) {
      video.pause();
      return;
    }
    try { await video.play(); }
    catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) setControlError("Playback could not start. Try playing the clip again.");
    }
  }

  async function toggleFullscreen() {
    setControlError(undefined);
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await monitor.current?.requestFullscreen();
    } catch {
      setControlError("Fullscreen is unavailable in this browser.");
    }
  }

  const ready = status === "ready";
  return <div ref={monitor} className="video-monitor playable-monitor">
    <video className="monitor-media" style={mediaAspect(ratio ?? intrinsicRatio)} aria-label={label}
      ref={player} playsInline preload="metadata" src={src} hidden={status === "error"}
      onLoadedMetadata={(event) => {
        const { videoWidth, videoHeight } = event.currentTarget;
        if (videoWidth && videoHeight) setIntrinsicRatio(videoWidth / videoHeight);
        setStatus("ready");
      }}
      onDurationChange={(event) => setDuration(Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0)}
      onTimeUpdate={(event) => setTime(event.currentTarget.currentTime)}
      onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)}
      onVolumeChange={(event) => { setVolume(event.currentTarget.volume); setMuted(event.currentTarget.muted); }}
      onError={() => setStatus("error")} />
    {status === "loading" && <p className="monitor-loading" role="status">Loading video…</p>}
    {status === "error" && <p className="monitor-error" role="alert">{local
      ? "This recording cannot play in the browser. You can still generate clips from it."
      : "This clip could not be played. Try reopening the job or downloading the clip."}</p>}
    {status !== "error" && <div className="player-controls" role="group" aria-label="Video controls">
      <button type="button" className="secondary-button play-toggle" disabled={!ready} onClick={() => void togglePlayback()}
        aria-label={playing ? "Pause video" : "Play video"} title={playing ? "Pause" : "Play"}>
        <span aria-hidden="true">{playing ? "Ⅱ" : "▶"}</span>
      </button>
      <input type="range" className="player-seek" aria-label="Seek video" aria-valuetext={formatTime(time)}
        min={0} max={duration} step={0.01} value={Math.min(time, duration)} disabled={!ready || !duration}
        onChange={(event) => { if (player.current) player.current.currentTime = Number(event.target.value); }} />
      <span className="player-time">{formatTime(time)} / {formatTime(duration)}</span>
      <div className="player-volume">
        <button type="button" className="secondary-button mute-toggle" disabled={!ready} aria-pressed={muted}
          onClick={() => { if (player.current) player.current.muted = !player.current.muted; }}>{muted ? "Unmute" : "Mute"}</button>
        <input type="range" aria-label="Volume" min={0} max={1} step={0.05} value={muted ? 0 : volume} disabled={!ready}
          onChange={(event) => {
            if (!player.current) return;
            player.current.muted = false;
            player.current.volume = Number(event.target.value);
          }} />
      </div>
      <button type="button" className="secondary-button fullscreen-toggle" disabled={!ready} onClick={() => void toggleFullscreen()}
        aria-label={fullscreen ? "Exit fullscreen" : "Enter fullscreen"} title={fullscreen ? "Exit fullscreen" : "Fullscreen"}><span aria-hidden="true">⛶</span></button>
      {controlError && <p className="inline-error" role="alert">{controlError}</p>}
    </div>}
  </div>;
}

export function LocalRecordingMonitor({ file }: { file: File }) {
  const [preview, setPreview] = useState<{ file: File; url: string }>();
  useEffect(() => {
    const url = URL.createObjectURL(file);
    setPreview({ file, url });
    return () => URL.revokeObjectURL(url);
  }, [file]);
  return preview?.file === file
    ? <VideoMonitor key={preview.url} src={preview.url} label={file.name} local />
    : <p role="status">Preparing local preview…</p>;
}

export function SourceFrameMonitor({ media, available }: { media: Media; available: boolean }) {
  const [time, setTime] = useState("0");
  const [frame, setFrame] = useState<{ url: string; time: number }>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => {
    if (!available) request.current?.abort();
  }, [available]);

  async function load(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const seconds = Number(time);
    if (!available || !Number.isFinite(seconds) || seconds < 0 || seconds >= media.duration) {
      setError("Choose a timestamp inside the recording.");
      return;
    }
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setError(undefined);
    setLoading(true);
    try {
      const job = await requestPreviewFrame(media.id, { time: seconds }, controller.signal);
      if (!controller.signal.aborted) setFrame({ url: apiPath(job.frame_url), time: seconds });
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Source preview failed.");
    } finally {
      if (request.current === controller) {
        request.current = null;
        setLoading(false);
      }
    }
  }

  if (!available) return <div className="monitor-empty"><p>Source files unavailable. Import the original recording to generate new clips.</p></div>;
  return <>
    <div className="video-monitor">
      {frame
        ? /* The source still is generated by the local processor. */
          <img className="monitor-media" style={mediaAspect(media.width / media.height)} src={frame.url}
            alt={`Source frame at ${formatTime(frame.time)}`} onError={() => { setFrame(undefined); setError("Could not load the source frame. Retry the preview."); }} />
        : <div className="monitor-empty"><span className="monitor-glyph" aria-hidden="true">▶</span>
          <h3>Source monitor</h3><p>Load a frame to inspect the recording.</p></div>}
      {loading && <p className="monitor-loading" role="status">Loading source frame…</p>}
    </div>
    <form className="source-monitor-controls" onSubmit={load}>
      <label>Frame time (s)<input type="number" min="0" step="any" required value={time}
        onChange={(event) => setTime(event.target.value)} disabled={loading} /></label>
      <button className="secondary-button" type="submit" disabled={loading}>Load source frame</button>
      {error && <p className="inline-error" role="alert">{error}</p>}
    </form>
  </>;
}
