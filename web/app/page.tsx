"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import FramingEditor from "../components/FramingEditor";
import { framingError } from "../lib/framing";
import { apiPath, apiRequest, ASPECT_RATIO_OPTIONS, COMPRESSION_OPTIONS, formatSize, formatTime, intervalError,
  isActive, outputDimensions, uploadFile, VIDEO_QUALITY_OPTIONS, type AspectRatio, type AssetDeletionResult,
  type Candidate, type Compression, type FramingOptions, type Job, type Media, type Resolution, type ReviewState } from "../lib/api";

type Connection = { state: "checking" | "online" | "offline" | "degraded"; message: string };
type Layout = "pad" | "crop";
type ExportSettings = { aspectRatio: AspectRatio; resolution: Resolution; compression: Compression };

function exportSettingsFromJob(job?: Job): ExportSettings {
  return {
    aspectRatio: job?.options.aspect_ratio ?? "9:16",
    resolution: job?.options.resolution ?? 720,
    compression: job?.options.compression ?? "balanced",
  };
}

function ExportControls({ settings, onChange, media, disabled, revision }: {
  settings: ExportSettings;
  onChange: (settings: ExportSettings) => void;
  media?: Media;
  disabled?: boolean;
  revision?: boolean;
}) {
  const { aspectRatio, resolution, compression } = settings;
  const { width, height } = outputDimensions(resolution, aspectRatio);
  const sourceBelowCanvas = media && (media.width < width || media.height < height);
  return <>
    <div className="form-grid two">
      <label>Aspect Ratio<select aria-label={revision ? "Revision aspect ratio" : undefined} value={aspectRatio}
        onChange={(event) => onChange({ ...settings, aspectRatio: event.target.value as AspectRatio })} disabled={disabled}>
        {ASPECT_RATIO_OPTIONS.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
      </select></label>
      <label>Video Quality<select aria-label={revision ? "Revision video quality" : undefined} value={resolution}
        onChange={(event) => onChange({ ...settings, resolution: Number(event.target.value) as Resolution })} disabled={disabled}>
        {VIDEO_QUALITY_OPTIONS.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
      </select></label>
    </div>
    <label>Compression<select aria-label={revision ? "Revision compression" : undefined} value={compression}
      onChange={(event) => onChange({ ...settings, compression: event.target.value as Compression })} disabled={disabled}>
      {COMPRESSION_OPTIONS.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
    </select></label>
    <p className="framing-help" aria-live="polite">Output dimensions {width} × {height} px
      {sourceBelowCanvas && <>. Source {media.width} × {media.height} is smaller in at least one dimension. A larger export cannot recover source detail.</>}
    </p>
  </>;
}

const phaseLabels: Record<string, string> = {
  queued: "Waiting in queue", starting: "Starting", analysis: "Analyzing audio",
  transcribing: "Transcribing speech", ranking: "Ranking candidates", rendering: "Rendering clips",
  done: "Complete", failed: "Failed", cancelled: "Cancelled", interrupted: "Interrupted",
  framing: "Analyzing and planning framing", reusing_transcript: "Reusing saved speech", preview: "Preparing source preview",
};

const assetStatusLabels: Record<Media["asset_status"], string> = {
  available: "",
  deleting: "Deleting files…",
  deleted: "Assets Deleted",
  deletion_incomplete: "Deletion Incomplete",
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong. Please retry.";
}

function StateBadge({ job }: { job: Job }) {
  return <span className={`state-badge state-${job.state}`}>
    <span className="status-dot" />{job.cancel_requested && isActive(job) ? "Cancelling" : job.state}
  </span>;
}

function CandidateCard({ candidate, duration, media, initialLayout, initialExportSettings, initialFraming, onReview, onRender }: {
  candidate: Candidate;
  duration: number;
  initialLayout: Layout;
  initialExportSettings: ExportSettings;
  media?: Media;
  initialFraming: FramingOptions | null;
  onReview: (id: string, review: ReviewState) => Promise<void>;
  onRender: (candidate: Candidate, start: number, end: number, layout: Layout, exportSettings: ExportSettings, framing: FramingOptions|null) => Promise<void>;
}) {
  const [start, setStart] = useState(String(candidate.start));
  const [end, setEnd] = useState(String(candidate.end));
  const [layout, setLayout] = useState<Layout>(initialLayout);
  const [exportSettings, setExportSettings] = useState(initialExportSettings);
  const [framing, setFraming] = useState<FramingOptions|null>(initialFraming);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const savedSize = outputDimensions(initialExportSettings.resolution, initialExportSettings.aspectRatio);
  const labels: Record<string, string> = { audio_peak: "Audio peak", audio_onset: "Audio change",
    speech_activity: "Speech activity", transcript_cues: "Transcript cues" };

  async function review(value: ReviewState) {
    setBusy(true);
    setError(null);
    try { await onReview(candidate.id, value); }
    catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }

  async function render(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const problem = intervalError(Number(start), Number(end), duration) || framingError(framing);
    if (problem) { setError(problem); return; }
    setBusy(true);
    setError(null);
    try { await onRender(candidate, Number(start), Number(end), layout, exportSettings, framing); }
    catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }

  return <article className={`candidate-card review-${candidate.review_state}`}>
    <div className="clip-player"><video controls playsInline preload="metadata" style={{ aspectRatio: `${savedSize.width} / ${savedSize.height}` }} aria-label={`Candidate from ${formatTime(candidate.start)} to ${formatTime(candidate.end)}`} src={apiPath(candidate.preview_url)} /></div>
    <div className="clip-content">
      <div className="clip-heading"><h3>{formatTime(candidate.start)} <span>—</span> {formatTime(candidate.end)}</h3>
        <span className={`review-label ${candidate.review_state}`}>{candidate.review_state}</span></div>
      <div className="clip-meta"><span>{(candidate.end - candidate.start).toFixed(1)} sec</span>
        <span>Heuristic score {candidate.score.toFixed(2)}</span></div>
      {candidate.framing&&<p className="framing-result">{candidate.framing.selected_mode.replaceAll("_"," ")}
        {candidate.framing.fallback_reason?` · ${candidate.framing.fallback_reason}`:` · framing confidence ${Math.round(candidate.framing.confidence*100)}% (heuristic/manual)`}
        {candidate.visual_analysis?.cache_hit?" · Visual analysis reused":""}</p>}
      <div className="review-actions">
        <button type="button" aria-pressed={candidate.review_state === "approved"} className="approve-button" disabled={busy}
          onClick={() => review(candidate.review_state === "approved" ? "proposed" : "approved")}>✓ Approve</button>
        <button type="button" aria-pressed={candidate.review_state === "rejected"} className="reject-button" disabled={busy}
          onClick={() => review(candidate.review_state === "rejected" ? "proposed" : "rejected")}>× Reject</button>
        <a className="download-button" href={apiPath(candidate.download_url)}>↓ Download</a>
      </div>
      <details className="clip-details"><summary>Adjust clip</summary>
        <form onSubmit={render} className="revision-form">
          <div className="form-grid two"><label>Start (seconds)<input aria-label="Revision start" type="number" step="any" min="0" max={duration} value={start} onChange={(event) => setStart(event.target.value)} required disabled={busy} /></label>
            <label>End (seconds)<input aria-label="Revision end" type="number" step="any" min="0" max={duration} value={end} onChange={(event) => setEnd(event.target.value)} required disabled={busy} /></label></div>
          {!framing&&<label>Layout<select aria-label="Revision layout" value={layout} onChange={(event) => setLayout(event.target.value as Layout)} disabled={busy}>
            <option value="pad">Fit full frame</option><option value="crop">Center crop</option></select></label>
          }
          <ExportControls settings={exportSettings} onChange={setExportSettings} media={media} disabled={busy} revision />
          <FramingEditor value={framing} onChange={setFraming} mediaId={media?.id} width={media?.width} height={media?.height}
            duration={duration} initialTime={candidate.start} ratio={exportSettings.aspectRatio} resolution={exportSettings.resolution}
            disabled={busy} plan={candidate.framing}/>
          <button type="submit" className="secondary-button" disabled={busy}>{busy ? "Saving…" : "Render revision"}</button>
        </form>
      </details>
      <details className="clip-details evidence"><summary>Why this candidate</summary>
        {candidate.evidence.contributions ? <dl>{Object.entries(candidate.evidence.contributions).map(([name, value]) =>
          <div key={name}><dt>{labels[name] || name}</dt><dd>{value.toFixed(3)}</dd></div>)}</dl> : <p>This interval was selected manually.</p>}
        {!!candidate.evidence.cue_matches?.length && <p>Matched cues · {candidate.evidence.cue_matches.join(", ")}</p>}
      </details>
      {candidate.has_subtitles && <a className="subtitle-link" href={apiPath(`/clips/${candidate.clip_id}/subtitles`)}>Download captions (.srt)</a>}
      {error && <p className="inline-error" role="alert">{error}</p>}
    </div>
  </article>;
}

export default function Workspace() {
  const [media, setMedia] = useState<Media[]>([]);
  const [archivedMedia, setArchivedMedia] = useState<Media[]>([]);
  const [archiveTarget, setArchiveTarget] = useState<Media | null>(null);
  const [projectAction, setProjectAction] = useState<string | null>(null);
  const [archiveError, setArchiveError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Media | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleteFailures, setDeleteFailures] = useState<AssetDeletionResult["failures"]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedMediaId, setSelectedMediaId] = useState<string | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [candidatesLoading, setCandidatesLoading] = useState(false);
  const [filter, setFilter] = useState<"all" | "approved">("all");
  const [connection, setConnection] = useState<Connection>({ state: "checking", message: "Connecting to processor" });
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadPercent, setUploadPercent] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [count, setCount] = useState("3");
  const [length, setLength] = useState("30");
  const [layout, setLayout] = useState<Layout>("pad");
  const [exportSettings, setExportSettings] = useState(() => exportSettingsFromJob());
  const { aspectRatio, resolution, compression } = exportSettings;
  const [framing, setFraming] = useState<FramingOptions|null>({mode:"auto",background:"blur",tracking_intensity:0.5,subtitle_position:"auto"});
  const [fps, setFps] = useState("30");
  const [speech, setSpeech] = useState("captions");
  const [language, setLanguage] = useState("auto");
  const [manual, setManual] = useState(false);
  const [manualStart, setManualStart] = useState("0");
  const [manualEnd, setManualEnd] = useState("30");
  const [candidateRefresh, setCandidateRefresh] = useState(0);
  const [workspaceKey, setWorkspaceKey] = useState(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const archiveDialog = useRef<HTMLDialogElement>(null);
  const deleteDialog = useRef<HTMLDialogElement>(null);
  const newRecordingButton = useRef<HTMLButtonElement>(null);
  const operation = useRef<AbortController | null>(null);
  const initialized = useRef(false);
  const workspaceVersion = useRef(0);
  const mutationVersion = useRef(0);
  const refreshWorkspace = useRef<(() => void) | null>(null);

  const selectedMedia = media.find((item) => item.id === selectedMediaId);
  const selectedJob = jobs.find((item) => item.id === selectedJobId);
  const recentJobs = jobs.filter((job) => job.media_id === selectedMediaId && job.kind !== "frame_preview");
  const selectedAssetStatus = selectedMedia?.asset_status ?? "available";
  const selectedAssetsAvailable = selectedAssetStatus === "available" &&
    !(deleteTarget && projectAction === selectedMediaId && deleteTarget.id === selectedMediaId);
  const shownCandidates = selectedAssetsAvailable
    ? candidates.filter((candidate) => filter === "all" || candidate.review_state === "approved")
    : [];
  const activeJobs = jobs.filter(isActive).length;
  const deleteBlocked = Boolean(deleteTarget && jobs.some((job) => job.media_id === deleteTarget.id && isActive(job)));

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    let inFlight = false;
    let ticks = 0;
    async function refresh(forceHealth = false) {
      if (inFlight || stopped) return;
      clearTimeout(timer);
      inFlight = true;
      setRefreshing(true);
      const version = mutationVersion.current;
      const checkHealth = forceHealth || ticks % 5 === 0;
      const results = await Promise.allSettled([
        apiRequest<Media[]>("/media?limit=100", { signal: controller.signal }),
        apiRequest<Job[]>("/jobs?limit=100", { signal: controller.signal }),
        apiRequest<Media[]>("/media?archived=true&limit=100", { signal: controller.signal }),
        checkHealth ? apiRequest("/health", { signal: controller.signal }) : Promise.resolve(null),
      ]);
      if (stopped) return;
      const [mediaResult, jobsResult, archivedResult, healthResult] = results;
      if (mediaResult.status === "fulfilled" && jobsResult.status === "fulfilled") {
        if (version === mutationVersion.current) {
          setMedia(mediaResult.value);
          setJobs(jobsResult.value);
          if (archivedResult.status === "fulfilled") {
            setArchivedMedia(archivedResult.value.filter((record) => Boolean(record.archived_at)));
          }
        }
        if (!initialized.current) {
          initialized.current = true;
          const latestJob = jobsResult.value.find(job=>job.kind!=="frame_preview");
          setSelectedMediaId(latestJob?.media_id || mediaResult.value[0]?.id || null);
          setSelectedJobId(latestJob?.id || null);
          setExportSettings(exportSettingsFromJob(latestJob));
        }
        if (checkHealth) setConnection(healthResult.status === "fulfilled"
          ? { state: "online", message: "Processor connected" }
          : { state: "degraded", message: errorMessage(healthResult.reason) });
      } else {
        setConnection({ state: "offline", message: "Cannot reach the local processor. Start the API and retry." });
        ticks = -1;
      }
      ticks += 1;
      inFlight = false;
      setRefreshing(false);
      timer = setTimeout(() => refresh(), 3000);
    }
    refreshWorkspace.current = () => { void refresh(true); };
    void refresh(true);
    return () => {
      stopped = true;
      controller.abort();
      clearTimeout(timer);
      operation.current?.abort();
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const version = workspaceVersion.current;
    const isCurrent = () => !controller.signal.aborted && version === workspaceVersion.current;
    setCandidates([]);
    if (!selectedJobId || selectedJob?.state !== "completed" || !selectedAssetsAvailable) {
      setCandidatesLoading(false);
      return;
    }
    setCandidatesLoading(true);
    apiRequest<Candidate[]>(`/jobs/${selectedJobId}/candidates`, { signal: controller.signal })
      .then((records) => { if (isCurrent()) setCandidates(records); })
      .catch((failure) => { if (isCurrent()) setError(errorMessage(failure)); })
      .finally(() => { if (isCurrent()) setCandidatesLoading(false); });
    return () => controller.abort();
  }, [selectedJobId, selectedJob?.state, selectedAssetsAvailable, candidateRefresh]);

  useEffect(() => {
    if (archiveTarget && !archiveDialog.current?.open) archiveDialog.current?.showModal();
  }, [archiveTarget]);

  useEffect(() => {
    if (deleteTarget && !deleteDialog.current?.open) deleteDialog.current?.showModal();
  }, [deleteTarget]);

  function changeWorkspace() {
    initialized.current = true;
    workspaceVersion.current += 1;
    setCandidates([]);
    setCandidatesLoading(false);
    setCandidateRefresh((value) => value + 1);
    setFilter("all");
    setError(null);
    setNotice(null);
  }

  function resetWorkspace() {
    changeWorkspace();
    setWorkspaceKey((value) => value + 1);
    operation.current = null;
    if (fileInput.current) fileInput.current.value = "";
    setSelectedMediaId(null);
    setSelectedJobId(null);
    setPendingFile(null);
    setBusy(false);
    setUploading(false);
    setUploadPercent(0);
    setDragging(false);
    setCount("3");
    setLength("30");
    setLayout("pad");
    setExportSettings(exportSettingsFromJob());
    setFraming({ mode: "auto", background: "blur", tracking_intensity: 0.5, subtitle_position: "auto" });
    setFps("30");
    setSpeech("captions");
    setLanguage("auto");
    setManual(false);
    setManualStart("0");
    setManualEnd("30");
  }

  async function archiveProject() {
    if (!archiveTarget || projectAction) return;
    const target = archiveTarget;
    setProjectAction(target.id);
    setArchiveError(null);
    try {
      const updated = await apiRequest<Media>(`/media/${target.id}/archive`, { method: "POST" });
      mutationVersion.current += 1;
      setMedia((records) => records.filter((record) => record.id !== updated.id));
      setArchivedMedia((records) => [updated, ...records.filter((record) => record.id !== updated.id)]);
      setJobs((records) => records.filter((job) => job.media_id !== updated.id));
      if (selectedMediaId === updated.id) resetWorkspace();
      archiveDialog.current?.close();
      newRecordingButton.current?.focus();
      setNotice(`Removed ${updated.filename} from history. You can restore it from Archived Projects.`);
      refreshWorkspace.current?.();
    } catch (failure) {
      setArchiveError(errorMessage(failure));
    } finally {
      setProjectAction(null);
    }
  }

  async function restoreProject(target: Media) {
    if (projectAction) return;
    setProjectAction(target.id);
    setError(null);
    setNotice(null);
    try {
      const updated = await apiRequest<Media>(`/media/${target.id}/restore`, { method: "POST" });
      mutationVersion.current += 1;
      setArchivedMedia((records) => records.filter((record) => record.id !== updated.id));
      setMedia((records) => [updated, ...records.filter((record) => record.id !== updated.id)]);
      document.getElementById("archived-projects-summary")?.focus();
      setNotice(`Restored ${updated.filename} to history.`);
      refreshWorkspace.current?.();
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setProjectAction(null);
    }
  }

  async function deleteProjectFiles() {
    if (!deleteTarget || projectAction || deleteBlocked) return;
    const target = deleteTarget;
    setProjectAction(target.id);
    setDeleteError(null);
    setDeleteFailures([]);
    try {
      const result = await apiRequest<AssetDeletionResult>(`/media/${target.id}/delete-assets`, {
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      });
      mutationVersion.current += 1;
      setMedia((records) => records.map((record) => record.id === target.id ? result.media : record));
      setArchivedMedia((records) => records.map((record) => record.id === target.id ? result.media : record));
      if (selectedMediaId === target.id) changeWorkspace();
      if (result.media.asset_status === "deleted") {
        deleteDialog.current?.close();
        newRecordingButton.current?.focus();
        setNotice(`Deleted managed files for ${target.filename}. The project remains in history.`);
      } else {
        setDeleteTarget(result.media);
        setDeleteFailures(result.failures);
        setDeleteError("Some project files could not be removed. Review the errors and retry cleanup.");
      }
      refreshWorkspace.current?.();
    } catch (failure) {
      setDeleteError(errorMessage(failure));
      refreshWorkspace.current?.();
    } finally {
      setProjectAction(null);
    }
  }

  function selectMedia(record: Media) {
    changeWorkspace();
    const latestJob = jobs.find((job) => job.media_id === record.id && job.kind !== "frame_preview");
    setSelectedMediaId(record.id);
    setSelectedJobId(latestJob?.id || null);
    setExportSettings(exportSettingsFromJob(latestJob));
    setPendingFile(null);
    setManualEnd(String(Math.min(30, record.duration)));
  }

  function selectJob(job: Job) {
    changeWorkspace();
    setSelectedMediaId(job.media_id);
    setSelectedJobId(job.id);
    setExportSettings(exportSettingsFromJob(job));
    setPendingFile(null);
  }

  function chooseFile(file: File | undefined) {
    if (!file || busy) return;
    if (!/\.(mp4|mkv)$/i.test(file.name) || file.size <= 0 || file.size > 100 * 1024 ** 3) {
      setError("Choose a nonempty MP4 or MKV recording up to 100 GB.");
      return;
    }
    changeWorkspace();
    setPendingFile(file);
    setSelectedMediaId(null);
    setSelectedJobId(null);
  }

  function acceptJob(job: Job, version: number) {
    mutationVersion.current += 1;
    setJobs((records) => [job, ...records.filter((record) => record.id !== job.id)]);
    if (version !== workspaceVersion.current) return;
    setSelectedMediaId(job.media_id);
    setSelectedJobId(job.id);
    setCandidates([]);
    setFilter("all");
  }

  async function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !selectedAssetsAvailable || (!pendingFile && !selectedMedia)) return;
    const framingProblem=framingError(framing);
    if(framingProblem){setError(framingProblem);return;}
    if (manual) {
      const problem = intervalError(Number(manualStart), Number(manualEnd), selectedMedia?.duration);
      if (problem) { setError(problem); return; }
    }
    const version = workspaceVersion.current;
    setBusy(true);
    setError(null);
    setNotice(null);
    const controller = new AbortController();
    operation.current = controller;
    try {
      let record = selectedMedia;
      if (pendingFile) {
        setUploading(true);
        setUploadPercent(0);
        record = await uploadFile(pendingFile, (percent) => {
          if (version === workspaceVersion.current) setUploadPercent(percent);
        }, controller.signal);
        mutationVersion.current += 1;
        setMedia((records) => [record!, ...records.filter((item) => item.id !== record!.id)]);
        if (version === workspaceVersion.current) {
          setSelectedMediaId(record.id);
          setPendingFile(null);
          setUploading(false);
        }
      }
      if (!record) throw new Error("Choose a recording first.");
      if (manual) {
        const problem = intervalError(Number(manualStart), Number(manualEnd), record.duration);
        if (problem) throw new Error(problem);
      }
      const job = await apiRequest<Job>("/jobs", { method: "POST", signal: controller.signal, body: JSON.stringify({
        media_id: record.id, max_clips: Number(count),
        clip_length: manual ? Number(manualEnd) - Number(manualStart) : Number(length), layout_mode: layout,
        aspect_ratio: aspectRatio, resolution, compression, fps: Number(fps), captions: speech === "captions",
        speech_ranking: speech !== "audio", language: speech === "audio" ? "auto" : language,
        ...(framing?{framing}:{}),
        ...(manual ? { start: Number(manualStart), end: Number(manualEnd) } : {}),
      }) });
      acceptJob(job, version);
      if (version === workspaceVersion.current) setNotice("Job queued. You can keep reviewing while it processes.");
    } catch (failure) {
      if (version === workspaceVersion.current) {
        if (failure instanceof Error && failure.name === "AbortError") setNotice("Upload cancelled.");
        else setError(errorMessage(failure));
      }
    } finally {
      if (operation.current === controller) operation.current = null;
      if (version === workspaceVersion.current) {
        setBusy(false);
        setUploading(false);
      }
    }
  }

  async function cancelJob(job: Job) {
    const version = workspaceVersion.current;
    setError(null);
    try {
      const updated = await apiRequest<Job>(`/jobs/${job.id}/cancel`, { method: "POST" });
      mutationVersion.current += 1;
      setJobs((records) => records.map((record) => record.id === updated.id ? updated : record));
    } catch (failure) {
      if (version === workspaceVersion.current) setError(errorMessage(failure));
    }
  }

  async function reviewCandidate(id: string, review_state: ReviewState) {
    const version = workspaceVersion.current;
    const updated = await apiRequest<Candidate>(`/candidates/${id}`, { method: "PATCH", body: JSON.stringify({ review_state }) });
    if (version === workspaceVersion.current) {
      setCandidates((records) => records.map((record) => record.id === id ? { ...record, ...updated } : record));
    }
  }

  async function renderCandidate(candidate: Candidate, start: number, end: number, layout_mode: Layout, settings: ExportSettings, framing: FramingOptions|null) {
    const version = workspaceVersion.current;
    setBusy(true);
    try {
      const job = await apiRequest<Job>(`/candidates/${candidate.id}/render`, { method: "POST", body: JSON.stringify({
        start, end, layout_mode, aspect_ratio: settings.aspectRatio, resolution: settings.resolution,
        compression: settings.compression, framing,
      }) });
      acceptJob(job, version);
      if (version === workspaceVersion.current) {
        setExportSettings(exportSettingsFromJob(job));
        setNotice("Revision queued. The original clip remains in job history.");
      }
    } finally {
      if (version === workspaceVersion.current) setBusy(false);
    }
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="Clipper0 home"><span className="brand-mark" aria-hidden="true">▥</span><span>Clipper0</span></a>
      <div className="workspace-label"><span className="workspace-dot" />Local workspace</div>
      <button ref={newRecordingButton} type="button" className="new-recording" onClick={resetWorkspace}><span aria-hidden="true">＋</span> New recording</button>
      <div className="sidebar-section-label">RECORDINGS <span>{media.length}</span></div>
      <nav className="recording-list" aria-label="Imported recordings">
        {media.length === 0 && <p className="sidebar-empty">Your imported recordings will appear here.</p>}
        {media.map((record) => <div key={record.id} className="project-row">
          <button type="button" disabled={busy || projectAction !== null} className={`recording-item ${record.id === selectedMediaId ? "selected" : ""}`}
            onClick={() => selectMedia(record)} title={record.filename} aria-pressed={record.id === selectedMediaId}>
            <span className="recording-icon" aria-hidden="true">▷</span><span className="recording-item-text"><strong>{record.filename}</strong>
              <small>{assetStatusLabels[record.asset_status] || <>{formatTime(record.duration)} <span>·</span> {formatSize(record.size_bytes)}</>}</small></span>
          </button>
          <details className="project-actions" onKeyDown={(event) => {
            if (event.key !== "Escape" || !event.currentTarget.open) return;
            event.preventDefault();
            event.currentTarget.open = false;
            event.currentTarget.querySelector("summary")?.focus();
          }}>
            <summary aria-label={`Actions for ${record.filename}`}>⋯</summary>
            <button type="button" disabled={busy || projectAction !== null} onClick={() => {
              setArchiveError(null);
              setArchiveTarget(record);
            }}>Remove from History</button>
            {record.asset_status !== "deleted" && <button type="button" className="project-danger"
              disabled={busy || projectAction !== null || record.asset_status === "deleting"}
              onClick={() => {
                setDeleteError(null);
                setDeleteFailures([]);
                setDeleteTarget(record);
              }}>Delete Project Files</button>}
          </details>
        </div>)}
      </nav>
      <details className="archived-projects">
        <summary id="archived-projects-summary">Archived Projects ({archivedMedia.length})</summary>
        {archivedMedia.length === 0 ? <p className="sidebar-empty">No archived projects.</p> :
          <ul>{archivedMedia.map((record) => <li key={record.id}>
            <span title={record.filename}>{record.filename}
              {assetStatusLabels[record.asset_status] && <small> · {assetStatusLabels[record.asset_status]}</small>}
            </span>
            <button type="button" disabled={projectAction !== null} onClick={() => void restoreProject(record)}>
              {projectAction === record.id ? "Restoring…" : "Restore"}
            </button>
          </li>)}</ul>}
      </details>
      <div className="sidebar-footer"><span className={`connection-dot ${connection.state}`} /><span>{connection.state === "online" ? "Processor connected" : connection.state === "checking" ? "Connecting…" : "Processor needs attention"}</span></div>
    </aside>
    <dialog ref={archiveDialog} className="project-dialog" aria-labelledby="archive-title"
      onClose={() => { setArchiveTarget(null); setArchiveError(null); }}
      onCancel={(event) => { if (projectAction) event.preventDefault(); }}>
      <h2 id="archive-title">Remove from History?</h2>
      <p><strong>{archiveTarget?.filename}</strong> will move to Archived Projects. Your original recording,
        generated clips, transcripts, and other files will stay intact. You can restore the project at any time.</p>
      {archiveError && <p role="alert">{archiveError}</p>}
      <div className="project-dialog-actions">
        <button type="button" autoFocus disabled={projectAction !== null} onClick={() => archiveDialog.current?.close()}>Cancel</button>
        <button type="button" disabled={projectAction !== null} onClick={() => void archiveProject()}>
          {projectAction ? "Removing…" : "Remove from History"}
        </button>
      </div>
    </dialog>
    <dialog ref={deleteDialog} className="project-dialog project-delete-dialog" aria-labelledby="delete-project-title"
      onClose={() => { setDeleteTarget(null); setDeleteError(null); setDeleteFailures([]); }}
      onCancel={(event) => { if (projectAction) event.preventDefault(); }}>
      <h2 id="delete-project-title">Permanently delete project files?</h2>
      <p><strong>{deleteTarget?.filename}</strong></p>
      <p>This permanently removes the app-managed recording copy and eligible generated clips, captions, transcripts,
        preview frames, manifests, and partial files from this project’s jobs.</p>
      <p>Your original recording and shared caches are preserved. The project stays in history with its asset status.</p>
      {deleteBlocked && <p role="status">This project has queued or running work. Wait for it to finish,
        or cancel the job and wait for it to stop before deleting files.</p>}
      {deleteError && <p role="alert">{deleteError}</p>}
      {deleteFailures.length > 0 && <ul className="project-delete-failures">{deleteFailures.map(({ asset, reason }) =>
        <li key={asset}><strong>{asset}</strong> — {reason}</li>)}</ul>}
      <div className="project-dialog-actions">
        <button type="button" autoFocus disabled={projectAction !== null} onClick={() => deleteDialog.current?.close()}>Cancel</button>
        <button type="button" className="project-danger" disabled={projectAction !== null || deleteBlocked}
          onClick={() => void deleteProjectFiles()}>{projectAction ? "Deleting…" : deleteTarget?.asset_status === "deletion_incomplete"
            ? "Retry permanent deletion" : "Permanently delete files"}</button>
      </div>
    </dialog>

    <main className="main-workspace">
      <header className="workspace-header"><div><div className="breadcrumb">WORKSPACE <span>/</span> RECORDINGS</div><h1>Clip workspace<span className="heading-dot">.</span></h1></div>
        <div className="header-actions">{activeJobs > 0 && <span className="active-count">{activeJobs} active {activeJobs === 1 ? "job" : "jobs"}</span>}
          <button type="button" className="refresh-button" disabled={refreshing} onClick={() => { refreshWorkspace.current?.(); setCandidateRefresh((value) => value + 1); }} aria-label="Refresh workspace"><span aria-hidden="true">↻</span> {refreshing ? "Syncing…" : "Refresh"}</button></div></header>

      {(connection.state === "offline" || connection.state === "degraded") && <section className="connection-banner" role="status"><div><strong>Processor unavailable</strong><p>{connection.message}</p>
        <code>.\.venv\Scripts\python.exe -m autoclip serve</code></div><button type="button" className="secondary-button" onClick={() => refreshWorkspace.current?.()}>Retry connection</button></section>}
      {error && <div className="message error-message" role="alert"><span>{error}</span><button type="button" onClick={() => setError(null)} aria-label="Dismiss error">×</button></div>}
      {notice && <div className="message notice-message" role="status"><span>{notice}</span><button type="button" onClick={() => setNotice(null)} aria-label="Dismiss notification">×</button></div>}

      <div className="workspace-grid">
        <section className="setup-panel" aria-labelledby="recording-heading">
          <div className="panel-heading"><h2 id="recording-heading">Recording</h2><span className="local-label">On this computer</span></div>
          {!selectedAssetsAvailable && <p role="status" className="inline-error">
            {assetStatusLabels[selectedAssetStatus] || "Deleting files…"} · Import the original recording to render new clips.
          </p>}
          <input ref={fileInput} type="file" accept=".mp4,.mkv,video/mp4,video/x-matroska" className="file-input" aria-label="Choose recording file" disabled={busy}
            onChange={(event) => { chooseFile(event.target.files?.[0]); event.target.value = ""; }} />
          <div className={`upload-zone ${dragging ? "dragging" : ""} ${pendingFile || selectedMedia ? "has-file" : ""}`}
            onDragOver={(event) => { event.preventDefault(); if (!busy) setDragging(true); }} onDragLeave={() => setDragging(false)}
            onDrop={(event) => { event.preventDefault(); setDragging(false); chooseFile(event.dataTransfer.files[0]); }}>
            <div className="upload-symbol" aria-hidden="true">↑</div>
            {pendingFile || selectedMedia ? <><h3 title={pendingFile?.name || selectedMedia?.filename}>{pendingFile?.name || selectedMedia?.filename}</h3>
              <p>{pendingFile ? `${formatSize(pendingFile.size)} · Ready to import` : `${formatTime(selectedMedia!.duration)} · ${selectedMedia!.width}×${selectedMedia!.height} · ${formatSize(selectedMedia!.size_bytes)}`}</p></>
              : <><h3>Drop your recording here</h3><p>MP4 or MKV · Stored locally</p></>}
            <button type="button" className="choose-button" disabled={busy} onClick={() => fileInput.current?.click()}>{pendingFile || selectedMedia ? "Choose another file" : "Choose recording"}<span aria-hidden="true">↗</span></button>
          </div>
          <form className="settings-form" onSubmit={generate}>
            <div className="settings-heading"><h3>Clip settings</h3></div>
            <ExportControls settings={exportSettings} onChange={setExportSettings} media={pendingFile ? undefined : selectedMedia} disabled={busy} />
            <div className="form-grid two">
              <label>Clip count<select value={count} onChange={(event) => setCount(event.target.value)} disabled={busy || manual}>
                <option value="1">Up to 1 clip</option>
                <option value="2">Up to 2 clips</option>
                <option value="3">Up to 3 clips</option>
                <option value="4">Up to 4 clips</option>
                <option value="5">Up to 5 clips</option>
                <option value="6">Up to 6 clips</option>
                <option value="7">Up to 7 clips</option>
                <option value="8">Up to 8 clips</option>
                <option value="9">Up to 9 clips</option>
                <option value="10">Up to 10 clips</option>
              </select></label>
              <label>Length (seconds)<input type="number" min="15" max="60" step="any" value={length} onChange={(event) => setLength(event.target.value)} required disabled={busy || manual} /></label>
              {!framing&&<label>Layout<select value={layout} onChange={(event) => setLayout(event.target.value as Layout)} disabled={busy}><option value="pad">Fit full frame</option><option value="crop">Center crop</option></select></label>}
              <label>Frame rate<select value={fps} onChange={(event) => setFps(event.target.value)} disabled={busy}><option value="30">30 FPS</option><option value="60">60 FPS</option></select></label>
              <label>Speech<select value={speech} onChange={(event) => setSpeech(event.target.value)} disabled={busy}><option value="captions">Captions + cues</option><option value="speech">Speech cues only</option><option value="audio">Audio only</option></select></label>
            </div>
            {speech !== "audio" && <label>Spoken language<input list="languages" value={language} pattern="auto|[a-z]{2,3}" onChange={(event) => setLanguage(event.target.value.toLowerCase())} required disabled={busy} title="Use auto or a language code such as en or bn" />
              <datalist id="languages"><option value="auto">Auto-detect</option><option value="en">English</option><option value="bn">Bengali</option><option value="hi">Hindi</option><option value="ar">Arabic</option><option value="es">Spanish</option><option value="fr">French</option><option value="de">German</option><option value="ja">Japanese</option><option value="zh">Chinese</option></datalist></label>}
            <FramingEditor key={workspaceKey} value={framing} onChange={setFraming} mediaId={selectedAssetsAvailable ? selectedMedia?.id : undefined} width={selectedMedia?.width} height={selectedMedia?.height}
              duration={selectedMedia?.duration} ratio={aspectRatio} resolution={resolution} disabled={busy}/>
            <label className="checkbox-label"><input type="checkbox" checked={manual} onChange={(event) => setManual(event.target.checked)} disabled={busy} />Choose timestamps manually</label>
            {manual && <div className="form-grid two"><label>Start (seconds)<input type="number" step="any" min="0" value={manualStart} onChange={(event) => setManualStart(event.target.value)} required disabled={busy} /></label>
              <label>End (seconds)<input type="number" step="any" min="0" value={manualEnd} onChange={(event) => setManualEnd(event.target.value)} required disabled={busy} /></label></div>}
            {uploading && <div className="upload-progress" role="status"><div><span>{uploadPercent === 100 ? "Validating recording…" : "Importing recording…"}</span><span>{uploadPercent}%</span></div><progress value={uploadPercent} max={100} aria-label="Upload progress" />
              <button type="button" className="text-button" onClick={() => operation.current?.abort()}>Cancel upload</button></div>}
            <button className="generate-button" type="submit" disabled={busy || !selectedAssetsAvailable || (!pendingFile && !selectedMedia) || connection.state !== "online"}>
              {busy ? (uploading ? "Importing…" : "Creating job…") : manual ? "Render selected interval" : "Generate candidates"}<span aria-hidden="true">↗</span></button>
          </form>
        </section>

        <section className="results-panel" aria-labelledby="candidates-heading">
          <div className="results-heading"><h2 id="candidates-heading">Candidate clips <span>{candidates.length}</span></h2>
            <div className="filter-tabs" aria-label="Filter candidates"><button type="button" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>All</button>
              <button type="button" aria-pressed={filter === "approved"} onClick={() => setFilter("approved")}>Approved {candidates.filter((candidate) => candidate.review_state === "approved").length}</button></div></div>
          {selectedJob && <div className={`job-status ${selectedJob.state}`}>
            <div className="job-status-top"><div><span className="job-kind">{selectedJob.source_candidate_id ? "TIMESTAMP REVISION" : "CANDIDATE RUN"}</span><h3>{phaseLabels[selectedJob.phase] || selectedJob.phase}</h3></div><StateBadge job={selectedJob} /></div>
            {isActive(selectedJob) && <><progress value={selectedJob.progress_pct} max={100} aria-label="Processing progress" /><div className="job-progress-footer"><span>{selectedJob.progress_pct}% · Stage progress</span>
              <button type="button" disabled={selectedJob.cancel_requested} onClick={() => cancelJob(selectedJob)}>{selectedJob.cancel_requested ? "Cancelling…" : "Cancel job"}</button></div></>}
            {selectedJob.error_message && <p role="alert" className="job-error">{selectedJob.error_message}</p>}
            {selectedJob.state === "completed" && <p className="job-complete-detail">{selectedJob.elapsed_seconds !== null ? `Processing time ${selectedJob.elapsed_seconds.toFixed(1)}s` : "Processing finished"}
              {selectedJob.caption_status === "no_speech" ? " · No speech detected" : selectedJob.language ? ` · ${selectedJob.language.toUpperCase()} speech` : ""}
              {selectedJob.transcript_cache_hit ? " · Transcript reused" : ""}</p>}
          </div>}

          {candidatesLoading ? <div className="empty-state" role="status"><div className="empty-symbol">↻</div><h3>Loading clips…</h3></div>
            : shownCandidates.length > 0 ? <div className="candidate-grid">{shownCandidates.map((candidate) => <CandidateCard key={candidate.id} candidate={candidate} duration={selectedMedia?.duration ?? candidate.end}
              media={selectedMedia} initialFraming={selectedJob?.options.framing||null}
              initialLayout={selectedJob?.options.layout || "pad"} initialExportSettings={exportSettingsFromJob(selectedJob)} onReview={reviewCandidate} onRender={renderCandidate} />)}</div>
            : <div className="empty-state"><div className="empty-film" aria-hidden="true"><span>▷</span></div>
              <h3>{filter === "approved" && candidates.length ? "No approved clips yet" : selectedJob && isActive(selectedJob) ? "Your clips are on their way" : selectedJob?.state === "completed" ? "No candidates found" : selectedJob?.state === "failed" || selectedJob?.state === "cancelled" ? "No clips available for this job" : "Your review starts here"}</h3>
              <p>{filter === "approved" && candidates.length ? "Approve a candidate to find it here." : selectedJob && isActive(selectedJob) ? "Progress updates automatically. You can return to this job later." : selectedJob?.diagnostic ? "No moment met the ranking threshold. Try a manual interval or another recording." : "Import a recording and generate candidates to preview, adjust, and download."}</p></div>}
        </section>
      </div>

      <section className="history-panel" aria-labelledby="history-heading"><div className="panel-heading"><h2 id="history-heading">Job history</h2><span>{selectedMedia ? selectedMedia.filename : "Select a recording to view its jobs"}</span></div>
        {recentJobs.length === 0 ? <p className="history-empty">Processing jobs will appear here, including after a restart.</p>
          : <div className="job-list">{recentJobs.map((job) => <button key={job.id} type="button" disabled={busy} className={`job-row ${job.id === selectedJobId ? "selected" : ""}`} aria-pressed={job.id === selectedJobId} onClick={() => selectJob(job)}>
            <span className="job-row-icon" aria-hidden="true">{job.source_candidate_id ? "↻" : "▷"}</span>
            <span className="job-row-name"><strong>{media.find((record) => record.id === job.media_id)?.filename || "Imported recording"}</strong><small>{job.source_candidate_id ? "Timestamp revision" : "Candidate run"} · {new Date(job.created_at).toLocaleString()}</small></span>
            <StateBadge job={job} /><span className="job-row-arrow" aria-hidden="true">↗</span></button>)}</div>}
      </section>
      <footer className="workspace-footer"><span>Clipper0</span><span>Review candidates before sharing.</span></footer>
    </main>
  </div>;
}
