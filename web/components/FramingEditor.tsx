"use client";

import { useEffect, useRef, useState, type PointerEvent } from "react";
import { apiPath, apiRequest, aspectRatioParts, outputDimensions, type AspectRatio, type FocusPoint, type FocusRegion, type FramingOptions, type FramingPlan, type Job, type Resolution } from "../lib/api";
import { cropPreview, framingError, normalizedPoint, plannedCrop, regionBetween } from "../lib/framing";

const defaults: FramingOptions = {mode:"auto",background:"blur",tracking_intensity:0.5,subtitle_position:"auto",emphasis_zoom:false};

export default function FramingEditor({value,onChange,mediaId,width=1920,height=1080,duration=0,initialTime=0,ratio,resolution=720,disabled=false,plan}: {
  value: FramingOptions|null; onChange:(value:FramingOptions|null)=>void; mediaId?:string;
  width?:number; height?:number; duration?:number; initialTime?:number; ratio:AspectRatio; resolution?:Resolution; disabled?:boolean; plan?:FramingPlan|null;
}) {
  const [time,setTime]=useState(String(initialTime));
  const [frame,setFrame]=useState<string|null>(null);
  const [frameTime,setFrameTime]=useState(initialTime);
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
    setFrameTime(initialTime);
    setTime(String(initialTime));
    setError(null);
  }, [mediaId, initialTime]);
  function update(patch:Partial<FramingOptions>) { onChange({...defaults,...value,...patch}); }
  async function loadFrame() {
    const seconds=Number(time);
    if(!mediaId || !Number.isFinite(seconds) || seconds<0 || seconds>=duration) {setError("Choose a timestamp inside the recording.");return;}
    setBusy(true);setError(null);request.current?.abort();
    const controller=new AbortController();request.current=controller;
    try {
      let job=await apiRequest<Job>(`/media/${mediaId}/frames`,{method:"POST",body:JSON.stringify({time:seconds}),signal:controller.signal});
      for(let i=0;i<600 && job.state!=="completed";i++) {
        if(job.state==="failed"||job.state==="cancelled") throw new Error(job.error_message||"Frame preview cancelled.");
        await new Promise<void>((resolve,reject)=>{const abort=()=>{clearTimeout(timer);reject(new DOMException("Cancelled","AbortError"));};const timer=setTimeout(()=>{controller.signal.removeEventListener("abort",abort);resolve();},500);if(controller.signal.aborted)abort();else controller.signal.addEventListener("abort",abort,{once:true});});
        job=await apiRequest<Job>(`/jobs/${job.id}`,{signal:controller.signal});
      }
      if (request.current !== controller || controller.signal.aborted) return;
      if(!job.frame_url) throw new Error("Preview is still queued. Retry after current processing finishes.");
      setFrame(apiPath(job.frame_url));
      setFrameTime(seconds);
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
    if(disabled||!value||!frame)return;
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
  const [ratioWidth, ratioHeight] = aspectRatioParts(ratio);
  const savedCrop = plan ? plannedCrop(plan, Math.max(0, frameTime - plan.start)) : null;
  const savedGeometry = plan?.keyframes[0]?.crop;
  const keepSavedCrop = savedGeometry && savedGeometry.width * ratioHeight === savedGeometry.height * ratioWidth;
  const savedFocus = savedCrop ? { x: savedCrop.x + savedCrop.width / 2, y: savedCrop.y + savedCrop.height / 2 } : null;
  const webcam = value?.mode === "streamer_gameplay" || value?.mode === "auto" ? value.webcam_region : null;
  const cropFocus = point ?? (keepSavedCrop ? null : savedFocus);
  const crop = value?.mode === "full_gameplay" || value?.mode === "streamer_gameplay" || webcam ? null :
    cropFocus ? cropPreview(width, height, ratio, cropFocus) : savedCrop;
  const region=draft||(target==="webcam"?value?.webcam_region:value?.focus_region);
  const problem=framingError(value);
  function regionInputs(key:"focus_region"|"webcam_region",title:string) {
    const selected=value?.[key];
    return <div className="region-controls"><div className="framing-inline"><span>{title}</span><button type="button" disabled={disabled} onClick={()=>update({[key]:selected?null:{x:0,y:0,width:0.2,height:0.2},...(key==="focus_region"?{focus_point:null}:{})})}>{selected?"Clear":"Set manually"}</button></div>
      {selected&&<div className="region-grid">{(["x","y","width","height"] as const).map(field=><label key={field}>{field}<input aria-label={`${title} ${field}`} type="number" min="0" max="1" step="0.01" value={selected[field]} disabled={disabled} onChange={event=>update({[key]:{...selected,[field]:Number(event.target.value)}})}/></label>)}</div>}</div>;
  }
  return <section className="framing-editor" aria-label="Smart reframing settings">
    <label>Framing mode<select value={value?.mode||"legacy"} disabled={disabled} onChange={event=>onChange(event.target.value==="legacy"?null:{...defaults,...value,mode:event.target.value as FramingOptions["mode"]})}>
      <option value="legacy">Basic fit / center crop</option><option value="auto">Auto · preserve when uncertain</option><option value="smart_crop">Smart tracking crop</option><option value="streamer_gameplay">Streamer + gameplay</option><option value="full_gameplay">Full gameplay</option></select></label>
    {value&&<>
      <div className="form-grid two"><label>Background<select value={value.background||"blur"} disabled={disabled} onChange={event=>update({background:event.target.value as "blur"|"pad"})}><option value="blur">Blurred</option><option value="pad">Padded</option></select></label>
      <label>Subtitle position<select value={value.subtitle_position||"auto"} disabled={disabled} onChange={event=>update({subtitle_position:event.target.value as FramingOptions["subtitle_position"]})}><option value="auto">Layout-aware</option><option value="top">Top</option><option value="center">Center</option><option value="bottom">Bottom</option></select></label></div>
      <label>Tracking intensity · {Math.round((value.tracking_intensity??0.5)*100)}%<input type="range" min="0" max="1" step="0.05" value={value.tracking_intensity??0.5} disabled={disabled} onChange={event=>update({tracking_intensity:Number(event.target.value)})}/></label>
      <label className="checkbox-label"><input type="checkbox" checked={value.emphasis_zoom||false} disabled={disabled} onChange={event=>update({emphasis_zoom:event.target.checked})}/>Subtle emphasis on confident events</label>
      <details><summary>Source preview and manual focus</summary><p className="framing-help">Click for a focus point or drag a region. Manual focus stays fixed; clear it to resume automatic tracking. Preview is a framing guide; review the rendered clip.</p>
        <div className="framing-inline"><label>Source time (s)<input type="number" min="0" max={Math.max(0,duration-0.01)} step="0.1" value={time} disabled={busy||disabled} onChange={event=>setTime(event.target.value)}/></label><button className="secondary-button" type="button" disabled={!mediaId||busy||disabled} onClick={()=>void loadFrame()}>{busy?"Queued / loading…":"Load frame"}</button></div>
        {!mediaId&&<p className="framing-help">Generate the first run to import your recording, then open Adjust clip to preview and refine it.</p>}
        <label>Selection tool<select value={target} disabled={disabled} onChange={event=>setTarget(event.target.value as typeof target)}><option value="point">Focus point</option><option value="region">Focus region</option><option value="webcam">Webcam region</option></select></label>
        {frame&&<><div className="source-frame" style={{aspectRatio:`${width} / ${height}`}} onPointerDown={begin} onPointerMove={event=>{if(drag.current&&target!=="point")setDraft(regionBetween(drag.current,coordinate(event)));}} onPointerUp={finish} onPointerCancel={()=>{drag.current=null;setDraft(null);}}>
          {/* A local generated still is interactive source material, not an optimized site image. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}<img src={frame} alt="Source frame for selecting focus and webcam regions" draggable={false}/>
          {crop&&<span className="crop-outline" style={{left:`${crop.x*100}%`,top:`${crop.y*100}%`,width:`${crop.width*100}%`,height:`${crop.height*100}%`}}/>}
          {region&&<span className="region-outline" style={{left:`${region.x*100}%`,top:`${region.y*100}%`,width:`${region.width*100}%`,height:`${region.height*100}%`}}/>}
          {point&&<span className="focus-cross" style={{left:`${point.x*100}%`,top:`${point.y*100}%`}}>＋</span>}
        </div><div className="safe-area-guide">Dashed frame: crop guide. Preview at {frameTime.toFixed(1)}s; final video remains the reference.</div>
        <div className="framing-output" style={{aspectRatio:`${outputWidth} / ${outputHeight}`}} aria-label={`Framing composition guide, ${outputWidth} by ${outputHeight} pixels`}>
          {webcam?<>
            <svg className="split-camera" viewBox={`${webcam.x*width} ${webcam.y*height} ${webcam.width*width} ${webcam.height*height}`}><image href={frame} width={width} height={height}/></svg>
            <svg className="split-game" viewBox={`0 0 ${width} ${height}`}><image href={frame} width={width} height={height}/></svg>
          </>:<svg viewBox={crop?`${crop.x*width} ${crop.y*height} ${crop.width*width} ${crop.height*height}`:`0 0 ${width} ${height}`}><image href={frame} width={width} height={height}/></svg>}
          <span className="output-safe-zone" style={{left:`${(value.safe_margin_horizontal??0.08)*100}%`,right:`${(value.safe_margin_horizontal??0.08)*100}%`,top:`${(value.safe_margin_top??0.08)*100}%`,bottom:`${(value.safe_margin_bottom??0.15)*100}%`}}/>
        </div></>}
        <div className="framing-inline"><span>Focus point</span><button type="button" disabled={disabled} onClick={()=>update({focus_point:point?null:{x:0.5,y:0.5},focus_region:null})}>{point?"Clear":"Set manually"}</button></div>
        {value.focus_point&&<div className="form-grid two">{(["x","y"] as const).map(field=><label key={field}>Focus {field}<input aria-label={`Focus ${field}`} type="number" min="0" max="1" step="0.01" value={value.focus_point![field]} disabled={disabled} onChange={event=>update({focus_point:{...value.focus_point!,[field]:Number(event.target.value)}})}/></label>)}</div>}
        {regionInputs("focus_region","Focus region")}{regionInputs("webcam_region","Webcam region")}
      </details>
      <details><summary>Caption safe margins</summary><div className="region-grid">{(["safe_margin_horizontal","safe_margin_top","safe_margin_bottom"] as const).map((field,index)=><label key={field}>{["Sides","Top","Bottom"][index]}<input type="number" min="0" max="0.4" step="0.01" value={value[field]??[0.08,0.08,0.15][index]} disabled={disabled} onChange={event=>update({[field]:Number(event.target.value)})}/></label>)}</div></details>
      <p className="framing-help">Local visual heuristics can miss subjects or webcams. Auto preserves the source when confidence is low. Motion alone is not importance.</p>
    </>}
    {(error||problem)&&<p className="inline-error" role="alert">{error||problem}</p>}
  </section>;
}
