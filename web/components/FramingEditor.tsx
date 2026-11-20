"use client";

import { useEffect, useRef, useState, type PointerEvent } from "react";
import { apiPath, apiRequest, DEFAULT_FRAMING, FRAMING_LABELS, intervalError, outputDimensions, processorErrorMessage, type AspectRatio, type FocusPoint, type FocusRegion, type FramingMode, type FramingOptions, type FramingPlan, type Job, type Resolution } from "../lib/api";
import { coversRegion, cropPreview, displayedFramingMode, framingError, normalizedPoint, plannedCrop, regionBetween, selectFramingMode, VISIBLE_FRAMING_MODES } from "../lib/framing";

export default function FramingEditor({value,onChange,mediaId,width=1920,height=1080,duration=0,initialTime=0,ratio,resolution=720,disabled=false,plan,original,interval}: {
  value: FramingOptions|null; onChange:(value:FramingOptions|null)=>void; mediaId?:string;
  width?:number; height?:number; duration?:number; initialTime?:number; ratio:AspectRatio; resolution?:Resolution; disabled?:boolean; plan?:FramingPlan|null;
  original?: { settings: FramingOptions | null; ratio: AspectRatio };
  interval?: { start: number; end: number };
}) {
  const [time,setTime]=useState(String(initialTime));
  const [frame,setFrame]=useState<string|null>(null);
  const [frameTime,setFrameTime]=useState(initialTime);
  const [rendered,setRendered]=useState<{url:string; key:string; mode?:FramingMode|null}|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<string|null>(null);
  const [target,setTarget]=useState<"point"|"region"|"webcam">("point");
  const [draft,setDraft]=useState<FocusRegion|null>(null);
  const drag=useRef<FocusPoint|null>(null);
  const request=useRef<AbortController|null>(null);
  useEffect(() => () => {
    request.current?.abort();
    request.current = null;
  }, []);
  useEffect(() => {
    request.current?.abort();
    request.current = null;
    setBusy(false);
    setFrame(null);
    setRendered(null);
    setFrameTime(initialTime);
    setTime(String(initialTime));
    setError(null);
  }, [mediaId, initialTime]);
  const composition = interval && value ? {...interval, framing:value, aspect_ratio:ratio, resolution} : undefined;
  const compositionKey = JSON.stringify([mediaId, Number(time), composition]);
  const exactPreview = rendered?.key === compositionKey ? rendered : null;
  function update(patch:Partial<FramingOptions>) { onChange({...DEFAULT_FRAMING,...value,...patch}); }
  async function loadFrame(kind: "source" | "composition") {
    const seconds=Number(time);
    if(!mediaId || !Number.isFinite(seconds) || seconds<0 || seconds>=duration) {setError("Choose a timestamp inside the recording.");return;}
    if (kind === "composition" && (!composition || intervalError(composition.start, composition.end, duration)
        || seconds < composition.start || seconds >= composition.end || framingError(value))) {
      setError("Choose valid framing settings and a preview time inside the 15–60 second clip.");
      return;
    }
    setBusy(true);setError(null);request.current?.abort();
    const controller=new AbortController();request.current=controller;
    try {
      let job=await apiRequest<Job>(`/media/${mediaId}/frames`,{method:"POST",
        body:JSON.stringify({time:seconds, ...(kind === "composition" ? {composition} : {})}),signal:controller.signal});
      for(let i=0;i<600 && job.state!=="completed";i++) {
        if (job.state === "failed") throw new Error(job.error_message ? processorErrorMessage(job.error_message) : "Frame preview failed. Try again.");
        if (job.state === "cancelled") throw new Error("Frame preview cancelled.");
        await new Promise<void>((resolve,reject)=>{const abort=()=>{clearTimeout(timer);reject(new DOMException("Cancelled","AbortError"));};const timer=setTimeout(()=>{controller.signal.removeEventListener("abort",abort);resolve();},500);if(controller.signal.aborted)abort();else controller.signal.addEventListener("abort",abort,{once:true});});
        job=await apiRequest<Job>(`/jobs/${job.id}`,{signal:controller.signal});
      }
      if (request.current !== controller || controller.signal.aborted) return;
      if(!job.frame_url) throw new Error("Preview is still queued. Retry after current processing finishes.");
      if (kind === "composition") {
        setRendered({url:apiPath(job.frame_url), key:compositionKey, mode:job.frame_framing_mode});
      } else {
        setFrame(apiPath(job.frame_url));
        setFrameTime(seconds);
      }
    } catch (failure) {
      if (request.current === controller && !controller.signal.aborted) {
        setError(failure instanceof Error ? failure.message : "Preview failed.");
      }
    } finally {
      if (request.current === controller) {
        request.current = null;
        setBusy(false);
      }
    }
  }
  function coordinate(event:PointerEvent<HTMLDivElement>) {
    const bounds=event.currentTarget.getBoundingClientRect();
    return normalizedPoint(event.clientX-bounds.left,event.clientY-bounds.top,bounds.width,bounds.height);
  }
  function begin(event:PointerEvent<HTMLDivElement>) {
    if(disabled||!value||!frame||(value.lock_position&&target!=="webcam"))return;
    event.preventDefault();event.currentTarget.setPointerCapture(event.pointerId);
    const point=coordinate(event);drag.current=point;
    if(target==="point")update({focus_point:point,focus_region:null});
  }
  function finish(event:PointerEvent<HTMLDivElement>) {
    if(!drag.current)return;
    const region=regionBetween(drag.current,coordinate(event));drag.current=null;setDraft(null);
    if(target!=="point" && region.width>=0.01 && region.height>=0.01) {
      if(target==="webcam")update({webcam_region:region});else update({focus_region:region,focus_point:null});
    }
  }
  const point=value?.focus_point|| (value?.focus_region?{x:value.focus_region.x+value.focus_region.width/2,y:value.focus_region.y+value.focus_region.height/2}:null);
  const { width: outputWidth, height: outputHeight } = outputDimensions(resolution, ratio);
  const usingSavedPlan = plan && original?.ratio === ratio && JSON.stringify(original.settings) === JSON.stringify(value)
    && interval?.start === plan.start && interval.end === plan.end &&
    frameTime >= plan.start && frameTime < plan.end;
  const savedCrop = usingSavedPlan ? plannedCrop(plan, frameTime - plan.start) : null;
  const webcam = value?.mode === "streamer_gameplay" || value?.mode === "auto" ? value.webcam_region : null;
  const manualAuto = value?.mode === "auto" && (value.auto_focus === false || value.lock_position);
  const spatial = value?.mode === "focus_crop" || value?.mode === "hybrid_focus";
  const zoomedAuto = value?.mode === "auto" && (value.foreground_zoom ?? 1) !== 1;
  const guideMode = manualAuto ? "hybrid_focus" : zoomedAuto ? "focus_crop" : value?.mode === "auto" ? "smart_crop" : value?.mode;
  const canCrop = !webcam && (spatial || manualAuto || !!point && value?.mode === "auto" || !!point && guideMode === "smart_crop");
  const preview = canCrop ? cropPreview(width, height, ratio, point ?? {x:0.5,y:0.5},
    guideMode, spatial || manualAuto || zoomedAuto ? value?.foreground_zoom : 1) : null;
  const focusRegion = value?.focus_region;
  let crop = usingSavedPlan ? savedCrop : preview;
  let draftMode = guideMode;
  if (!usingSavedPlan && crop && focusRegion && !coversRegion(crop, focusRegion)) {
    crop = null;
    if (value?.mode === "auto" && !manualAuto && point) {
      const hybrid = cropPreview(width, height, ratio, point, "hybrid_focus", value.foreground_zoom);
      if (coversRegion(hybrid, focusRegion)) {
        crop = hybrid;
        draftMode = "hybrid_focus";
      }
    }
  }
  const displayedMode = usingSavedPlan ? plan.selected_mode : crop ? draftMode : "full_gameplay";
  const lockCenter = crop ? {x:crop.x+crop.width/2,y:crop.y+crop.height/2} : {x:0.5,y:0.5};
  const canPosition = value && value.mode !== "full_gameplay" && value.mode !== "streamer_gameplay";
  function setPosition(axis: "x" | "y", position: number) {
    update({focus_point:{...(point ?? lockCenter),[axis]:position},focus_region:null});
  }
  const region=draft||(target==="webcam"?value?.webcam_region:value?.focus_region);
  const problem=framingError(value);
  const selectedMode = displayedFramingMode(value);
  function changeMode(selection: string) {
    const next = selectFramingMode(value, selection);
    if (next !== value) onChange(next);
  }
  function regionInputs(key:"focus_region"|"webcam_region",title:string) {
    const selected=value?.[key];
    const locked = disabled || (key === "focus_region" && !!value?.lock_position);
    return <div className="region-controls"><div className="framing-inline"><span>{title}</span><button type="button" disabled={locked} onClick={()=>update({[key]:selected?null:{x:0,y:0,width:0.2,height:0.2},...(key==="focus_region"?{focus_point:null}:{})})}>{selected?"Clear":"Set manually"}</button></div>
      {selected&&<div className="region-grid">{(["x","y","width","height"] as const).map(field=><label key={field}>{field}<input aria-label={`${title} ${field}`} type="number" min="0" max="1" step="0.01" value={selected[field]} disabled={locked} onChange={event=>update({[key]:{...selected,[field]:Number(event.target.value)}})}/></label>)}</div>}</div>;
  }
  return <section className="framing-editor" aria-label="Framing">
    <h3 className="settings-heading">Framing</h3>
    <label>Framing mode<select value={selectedMode} disabled={disabled} onChange={event=>changeMode(event.target.value)}>
      {VISIBLE_FRAMING_MODES.map(mode=><option key={mode} value={mode}>{FRAMING_LABELS[mode]}</option>)}
    </select></label>
    {value?.mode !== selectedMode && <div className="framing-inline">
      <p className="framing-help">Saved framing is active.</p>
      <button type="button" className="secondary-button" disabled={disabled} onClick={()=>changeMode(selectedMode)}>
        Use {FRAMING_LABELS[selectedMode]}
      </button>
    </div>}
    {value&&<>
      <div className="form-grid two"><label>Background<select value={value.background||"blur"} disabled={disabled} onChange={event=>update({background:event.target.value as "blur"|"pad"})}><option value="blur">Blurred</option><option value="pad">Padded</option></select></label>
      <label>Subtitle position<select value={value.subtitle_position||"auto"} disabled={disabled} onChange={event=>update({subtitle_position:event.target.value as FramingOptions["subtitle_position"]})}><option value="auto">Layout-aware</option><option value="top">Top</option><option value="center">Center</option><option value="bottom">Bottom</option></select></label></div>
      {canPosition&&<>
        {(spatial || value.mode === "auto")&&<label>Foreground zoom · {(value.foreground_zoom??1).toFixed(2)}×
          <input type="range" min="1" max="2" step="0.05" value={value.foreground_zoom??1} disabled={disabled}
            onChange={event=>update({foreground_zoom:Number(event.target.value)})}/></label>}
        <div className="form-grid two">
          {(["x","y"] as const).map(axis=><label key={axis}>{axis==="x"?"Horizontal crop position":"Vertical crop position"} · {Math.round((point ?? lockCenter)[axis]*100)}%
            <input type="range" min="0" max="1" step="0.01" value={(point ?? lockCenter)[axis]} disabled={disabled||value.lock_position}
              onChange={event=>setPosition(axis, Number(event.target.value))}/></label>)}
        </div>
      </>}
      <details className="advanced-framing">
        <summary>Advanced Framing</summary>
        <div className="advanced-framing-controls">
      {canPosition&&<label className="checkbox-label"><input type="checkbox" checked={value.lock_position??false} disabled={disabled}
        onChange={event=>update(event.target.checked?{lock_position:true,focus_point:point??lockCenter,focus_region:null}:{lock_position:false})}/>Lock crop position</label>}
      {value.mode!=="full_gameplay"&&<>
        <label className="checkbox-label"><input type="checkbox" checked={value.auto_focus??true} disabled={disabled||value.lock_position}
          onChange={event=>update({auto_focus:event.target.checked})}/>Auto Focus</label>
        <label className="checkbox-label"><input type="checkbox" checked={value.smooth_tracking??true}
          disabled={disabled||value.lock_position||value.auto_focus===false||!!value.focus_point}
          onChange={event=>update({smooth_tracking:event.target.checked})}/>Smooth tracking</label>
        <label>Tracking intensity · {Math.round((value.tracking_intensity??0.5)*100)}%<input type="range" min="0" max="1" step="0.05" value={value.tracking_intensity??0.5}
          disabled={disabled||value.lock_position||value.auto_focus===false||value.smooth_tracking===false||!!value.focus_point}
          onChange={event=>update({tracking_intensity:Number(event.target.value)})}/></label>
      </>}
      <label className="checkbox-label"><input type="checkbox" checked={value.emphasis_zoom||false} disabled={disabled} onChange={event=>update({emphasis_zoom:event.target.checked})}/>Subtle emphasis on confident events</label>
      <button className="secondary-button" type="button" disabled={disabled} onClick={()=>onChange({
        ...DEFAULT_FRAMING, background:value.background, subtitle_position:value.subtitle_position,
        safe_margin_horizontal:value.safe_margin_horizontal,safe_margin_top:value.safe_margin_top,
        safe_margin_bottom:value.safe_margin_bottom,
      })}>Reset framing</button>
      <details className="framing-disclosure"><summary>Source preview and manual focus</summary><p className="framing-help">Drag a focus point or draw a region to keep it visible. Clear the point to resume Auto Focus.</p>
        <div className="framing-inline preview-actions"><label>Source time (s)<input type="number" min="0" max={Math.max(0,duration-0.01)} step="any" value={time} disabled={busy||disabled} onChange={event=>setTime(event.target.value)}/></label><button className="secondary-button" type="button" disabled={!mediaId||busy||disabled} onClick={()=>void loadFrame("source")}>Load source frame</button>
        {composition&&<button className="secondary-button" type="button" disabled={!mediaId||busy||disabled} onClick={()=>void loadFrame("composition")}>Render preview frame</button>}
        {busy&&<span role="status">Preparing preview…</span>}</div>
        {!mediaId&&<p className="framing-help">Import a recording to preview its frames.</p>}
        <label>Selection tool<select value={target} disabled={disabled} onChange={event=>setTarget(event.target.value as typeof target)}><option value="point">Focus point</option><option value="region">Focus region</option><option value="webcam">Webcam region</option></select></label>
        {frame&&<><div className="source-frame" style={{aspectRatio:`${width} / ${height}`}} onPointerDown={begin} onPointerMove={event=>{
          if(!drag.current)return;
          const position=coordinate(event);
          if(target==="point")update({focus_point:position,focus_region:null});
          else setDraft(regionBetween(drag.current,position));
        }} onPointerUp={finish} onPointerCancel={()=>{drag.current=null;setDraft(null);}}>
          {/* A local generated still is interactive source material, not an optimized site image. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}<img src={frame} alt="Source frame for selecting focus and webcam regions" draggable={false}/>
          {crop&&<span className="crop-outline" style={{left:`${crop.x*100}%`,top:`${crop.y*100}%`,width:`${crop.width*100}%`,height:`${crop.height*100}%`}}/>}
          {region&&<span className="region-outline" style={{left:`${region.x*100}%`,top:`${region.y*100}%`,width:`${region.width*100}%`,height:`${region.height*100}%`}}/>}
          {point&&<span className="focus-cross" style={{left:`${point.x*100}%`,top:`${point.y*100}%`}}>＋</span>}
        </div><div className="safe-area-guide">Dashed crop guide at {frameTime.toFixed(1)}s.</div></>}
        {(frame||exactPreview)&&<div className="framing-output"
          style={{aspectRatio:`${outputWidth} / ${outputHeight}`,width:`min(100%, 200px, ${240*outputWidth/outputHeight}px)`}}
          aria-label={`Framing composition guide, ${outputWidth} by ${outputHeight} pixels`}>
          {exactPreview?
            // eslint-disable-next-line @next/next/no-img-element
            <img src={exactPreview.url} alt="FFmpeg-rendered framing preview"/> :
          webcam?<>
            <svg className="split-camera" viewBox={`${webcam.x*width} ${webcam.y*height} ${webcam.width*width} ${webcam.height*height}`}><image href={frame??undefined} width={width} height={height}/></svg>
            <svg className="split-game" viewBox={`0 0 ${width} ${height}`}><image href={frame??undefined} width={width} height={height}/></svg>
          </>:<>
            {(value.background??"blur")==="blur"&&(displayedMode==="hybrid_focus"||displayedMode==="full_gameplay")&&
              <svg className="framing-guide-background" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid slice"><image href={frame??undefined} width={width} height={height}/></svg>}
            <svg className="framing-guide-foreground" viewBox={crop?`${crop.x*width} ${crop.y*height} ${crop.width*width} ${crop.height*height}`:`0 0 ${width} ${height}`}>
              {crop?<svg x={crop.x*width} y={crop.y*height} width={crop.width*width} height={crop.height*height} viewBox={`${crop.x*width} ${crop.y*height} ${crop.width*width} ${crop.height*height}`} overflow="hidden"><image href={frame??undefined} width={width} height={height}/></svg>:
                <image href={frame??undefined} width={width} height={height}/>}
            </svg>
          </>}
          <span className="output-safe-zone" style={{left:`${(value.safe_margin_horizontal??0.08)*100}%`,right:`${(value.safe_margin_horizontal??0.08)*100}%`,top:`${(value.safe_margin_top??0.08)*100}%`,bottom:`${(value.safe_margin_bottom??0.15)*100}%`}}/>
        </div>}
        {exactPreview&&<p className="framing-help">Rendered {exactPreview.mode?FRAMING_LABELS[exactPreview.mode]:"composition"} at {Number(time).toFixed(2)}s. Caption guides are shown over the still.</p>}
        <div className="framing-inline"><span>Focus point</span><button type="button" disabled={disabled||value.lock_position} onClick={()=>update({focus_point:point?null:{x:0.5,y:0.5},focus_region:null})}>{point?"Clear":"Set manually"}</button></div>
        {regionInputs("focus_region","Focus region")}{regionInputs("webcam_region","Webcam region")}
      </details>
      <details className="framing-disclosure"><summary>Caption safe margins</summary><div className="region-grid">{(["safe_margin_horizontal","safe_margin_top","safe_margin_bottom"] as const).map((field,index)=><label key={field}>{["Sides","Top","Bottom"][index]}<input type="number" min="0" max="0.4" step="0.01" value={value[field]??[0.08,0.08,0.15][index]} disabled={disabled} onChange={event=>update({[field]:Number(event.target.value)})}/></label>)}</div></details>
        </div>
      </details>
      {value.mode==="auto"&&<p className="framing-help">Auto uses Full Frame when the visual evidence is uncertain.</p>}
    </>}
    {(error||problem)&&<p className="inline-error" role="alert">{error||problem}</p>}
  </section>;
}
