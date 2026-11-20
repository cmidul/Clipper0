import assert from "node:assert/strict";
import test from "node:test";
import { DEFAULT_FRAMING, FRAMING_LABELS, type FramingOptions } from "../lib/api.ts";
import { coversRegion, cropPreview, displayedFramingMode, framingError, normalizedPoint, plannedCrop, regionBetween,
  selectFramingMode, VISIBLE_FRAMING_MODES } from "../lib/framing.ts";

test("new clips can select exactly four framing modes", () => {
  assert.deepEqual(VISIBLE_FRAMING_MODES.map(mode => FRAMING_LABELS[mode]), [
    "Focus Crop", "Hybrid Focus", "Full Frame", "Auto",
  ]);
  for (const mode of VISIBLE_FRAMING_MODES) {
    const settings = selectFramingMode(DEFAULT_FRAMING, mode);
    assert.deepEqual(settings, { ...DEFAULT_FRAMING, mode });
    assert.equal(displayedFramingMode(settings), mode);
    assert.equal(framingError(settings), null);
  }
  for (const mode of ["streamer_gameplay", "smart_crop", "legacy", "unknown"]) {
    assert.equal(selectFramingMode(DEFAULT_FRAMING, mode), DEFAULT_FRAMING);
  }
});

test("legacy settings keep their saved values until a visible mode is selected", () => {
  const projects: [FramingOptions | null, string][] = [
    [{ mode: "smart_crop", focus_point: { x: 0.25, y: 0.5 } }, "focus_crop"],
    [{ mode: "streamer_gameplay", subtitle_position: "top", webcam_region: { x: 0, y: 0, width: 0.2, height: 0.2 } }, "full_gameplay"],
    [null, "full_gameplay"],
  ];
  for (const [saved, fallback] of projects) {
    const original = JSON.stringify(saved);
    assert.equal(displayedFramingMode(saved), fallback);
    assert.equal(selectFramingMode(saved, "legacy"), saved);
    assert.equal(framingError(saved), null);
    assert.deepEqual(selectFramingMode(saved, fallback), { ...DEFAULT_FRAMING, ...saved, mode: fallback });
    assert.equal(JSON.stringify(saved), original);
  }
});

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
test("Hybrid Focus retains a wider region and zoom stays in bounds", () => {
  const point = {x: 1, y: 1};
  const focus = cropPreview(1920, 1080, "9:16", point, "focus_crop");
  const hybrid = cropPreview(1920, 1080, "9:16", point, "hybrid_focus");
  const zoomed = cropPreview(1920, 1080, "9:16", point, "hybrid_focus", 1.5);
  const region = {x: 0.59, y: 0.75, width: 0.4, height: 0.2};
  assert.ok(hybrid.width > focus.width);
  assert.ok(zoomed.width < hybrid.width && zoomed.height < hybrid.height);
  assert.equal(zoomed.x + zoomed.width, 1);
  assert.equal(zoomed.y + zoomed.height, 1);
  assert.ok(coversRegion(hybrid, region));
  assert.ok(!coversRegion(focus, region));
  assert.ok(framingError({mode: "hybrid_focus", foreground_zoom: 2.1}));
});
test("plan preview interpolates within scenes and jumps only at cuts",()=>{
  const plan={start:0,end:15,source_width:1000,source_height:1000,selected_mode:"smart_crop" as const,confidence:1,fallback_reason:null,
    keyframes:[{time:0,scene_id:0,crop:{x:0,y:0,width:200,height:400}},{time:10,scene_id:0,crop:{x:400,y:0,width:200,height:400}}]};
  assert.ok(Math.abs(plannedCrop(plan,5)!.x-0.2)<0.003);
  plan.keyframes[1].scene_id=1;
  assert.equal(plannedCrop(plan,5)!.x,0);
  assert.equal(plannedCrop(plan,10)!.x,0.4);
});
