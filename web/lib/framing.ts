import { aspectRatioParts, type AspectRatio, type FocusPoint, type FocusRegion, type FramingOptions, type FramingPlan } from "./api.ts";

export function normalizedPoint(x: number, y: number, width: number, height: number): FocusPoint {
  if (![x,y,width,height].every(Number.isFinite) || width <= 0 || height <= 0) throw new Error("Invalid preview dimensions.");
  return { x: Math.min(1, Math.max(0, x / width)), y: Math.min(1, Math.max(0, y / height)) };
}

export function regionBetween(a: FocusPoint, b: FocusPoint): FocusRegion {
  return { x: Math.min(a.x,b.x), y: Math.min(a.y,b.y), width: Math.abs(a.x-b.x), height: Math.abs(a.y-b.y) };
}

export function framingError(value: FramingOptions | null): string | null {
  if (!value) return null;
  const point = value.focus_point;
  if (point && (![point.x,point.y].every(Number.isFinite) || point.x < 0 || point.y < 0 || point.x > 1 || point.y > 1)) return "Focus coordinates must be between 0 and 1.";
  for (const region of [value.focus_region, value.webcam_region]) {
    if (region && (![region.x,region.y,region.width,region.height].every(Number.isFinite)
      || region.x < 0 || region.y < 0 || region.width <= 0 || region.height <= 0
      || region.x+region.width > 1.000000001 || region.y+region.height > 1.000000001)) return "Regions must have positive size and stay inside the source.";
  }
  return null;
}

export function cropPreview(width: number, height: number, ratio: AspectRatio, point: FocusPoint): FocusRegion {
  const [rw,rh] = aspectRatioParts(ratio);
  const units = Math.floor(Math.min(width/(2*rw),height/(2*rh)));
  if (units < 1) return {x:0,y:0,width:1,height:1};
  const cw=rw*2*units, ch=rh*2*units;
  const x=Math.min(Math.floor((width-cw)/2)*2,Math.max(0,Math.round((point.x*width-cw/2)/2)*2));
  const y=Math.min(Math.floor((height-ch)/2)*2,Math.max(0,Math.round((point.y*height-ch/2)/2)*2));
  return {x:x/width,y:y/height,width:cw/width,height:ch/height};
}

export function plannedCrop(plan: FramingPlan, time: number): FocusRegion | null {
  const frames=plan.keyframes;
  if (!frames.length) return null;
  let crop=frames[0].crop;
  for (let i=1;i<frames.length;i++) {
    const a=frames[i-1],b=frames[i];
    if (time >= b.time) { crop=b.crop; continue; }
    if (time >= a.time && a.scene_id===b.scene_id) {
      const p=(time-a.time)/(b.time-a.time),alpha=0.5-0.5*Math.cos(Math.PI*p);
      crop={...a.crop,x:2*Math.floor((a.crop.x+(b.crop.x-a.crop.x)*alpha)/2),y:2*Math.floor((a.crop.y+(b.crop.y-a.crop.y)*alpha)/2)};
    }
    break;
  }
  return {x:crop.x/plan.source_width,y:crop.y/plan.source_height,width:crop.width/plan.source_width,height:crop.height/plan.source_height};
}
