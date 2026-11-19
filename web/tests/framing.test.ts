import assert from "node:assert/strict";
import test from "node:test";
import { cropPreview, framingError, normalizedPoint, plannedCrop, regionBetween } from "../lib/framing.ts";

test("pointer coordinates clamp and drag direction preserves valid regions",()=>{
  assert.deepEqual(normalizedPoint(-20,200,100,100),{x:0,y:1});
  assert.throws(()=>normalizedPoint(0,0,0,100));
  assert.deepEqual(regionBetween({x:0.8,y:0.7},{x:0.2,y:0.1}),{x:0.2,y:0.1,width:0.6000000000000001,height:0.6});
});
test("crop guide retains exact pixel geometry at source edges for all four ratios",()=>{
  const ratios = [["9:16", 9 / 16], ["16:9", 16 / 9], ["1:1", 1], ["4:5", 4 / 5]] as const;
  for(const [ratio, expected] of ratios) for(const x of [0,0.5,1]) {
    const crop=cropPreview(1920,1080,ratio,{x,y:0.5});
    assert.ok(crop.x>=0&&crop.y>=0&&crop.x+crop.width<=1&&crop.y+crop.height<=1);
    assert.ok(Math.abs(crop.width*1920/(crop.height*1080)-expected)<1e-9);
  }
});
test("manual coordinates are validated and split accepts a valid webcam region",()=>{
  assert.equal(framingError({mode:"streamer_gameplay",webcam_region:{x:0,y:0,width:0.2,height:0.2}}),null);
  assert.ok(framingError({mode:"smart_crop",focus_point:{x:NaN,y:0.5}}));
  assert.ok(framingError({mode:"auto",webcam_region:{x:0.9,y:0,width:0.2,height:0.2}}));
  assert.equal(framingError(null),null);
  assert.equal(framingError({mode:"auto"}),null);
});
test("plan preview interpolates within scenes and jumps only at cuts",()=>{
  const plan={start:0,end:15,source_width:1000,source_height:1000,selected_mode:"smart_crop" as const,confidence:1,fallback_reason:null,
    keyframes:[{time:0,scene_id:0,crop:{x:0,y:0,width:200,height:400}},{time:10,scene_id:0,crop:{x:400,y:0,width:200,height:400}}]};
  assert.ok(Math.abs(plannedCrop(plan,5)!.x-0.2)<0.003);
  plan.keyframes[1].scene_id=1;
  assert.equal(plannedCrop(plan,5)!.x,0);
  assert.equal(plannedCrop(plan,10)!.x,0.4);
});
