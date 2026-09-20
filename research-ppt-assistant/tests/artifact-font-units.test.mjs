import test from 'node:test';
import assert from 'node:assert/strict';
import { adaptArtifactToolTelemetry } from '../server/renderer-adapters/artifact-tool.mjs';
import { evaluateLegacyReadability } from '../server/visual-quality/rules/legacy-readability.mjs';
import fs from 'node:fs';
import { evaluateVisualQuality } from '../server/visual-quality/index.mjs';
const profile=JSON.parse(fs.readFileSync(new URL('../server/visual-quality/profiles/default.json',import.meta.url),'utf8'));
function adapt(size, fallback=false) {
  return adaptArtifactToolTelemetry({schema:'openai.presentation.layout/v4',
    slide:{aid:'sl/font',frame:{width:1280,height:720}},elements:[{
      aid:'sh/body',name:'body',kind:'shape',bbox:[80,160,500,250],text:'正文',
      ...(fallback ? {} : {resolvedFontSize:size}),
      resolvedTextStyle:{fontSize:fallback ? size : 99,color:'#000000'},
      textLayout:{lineCount:1,overflow:false},
    }]});
}
test('artifact CSS px convert once to canonical points, including fallback',()=>{
  assert.equal(adapt(18).elements[0].text.font_size,13.5);
  assert.equal(adapt(24).elements[0].text.font_size,18);
  assert.equal(adapt(24,true).elements[0].text.font_size,18);
  assert.equal(adapt(null,true).elements[0].text.font_size,null);
});
test('native QA opts into projector floors without legacy density checks', async()=>{
  const input={telemetry:adapt(18),context:{enforce_typography:true}};
  const report=await evaluateVisualQuality(input);
  assert.equal(report.checks.projector_typography.status,'fail');
  assert.ok(report.violations.some(v=>v.code==='FONT_FLOOR_VIOLATION'));
  assert.ok(!report.violations.some(v=>v.code==='MISSING_OCCUPANCY_TELEMETRY'));
  const disabled=await evaluateVisualQuality({telemetry:adapt(18)});
  assert.equal(disabled.checks.projector_typography,undefined);
  const fixed=await evaluateVisualQuality({...input,telemetry:adapt(24)});
  assert.equal(fixed.checks.projector_typography.status,'pass');
  const missing=await evaluateVisualQuality({...input,telemetry:adapt(null,true)});
  assert.equal(missing.checks.projector_typography.status,'not_evaluable');
});
test('Slide11 18px body cannot pass a 16pt projector floor',()=>{
  const old=evaluateLegacyReadability(adapt(18),profile,{viewing_mode:'projector'});
  assert.ok(old.violations.some(v=>v.code==='FONT_FLOOR_VIOLATION'));
  const fixed=evaluateLegacyReadability(adapt(24),profile,{viewing_mode:'projector'});
  assert.ok(!fixed.violations.some(v=>['FONT_FLOOR_VIOLATION','FONT_BELOW_VIEWING_TARGET'].includes(v.code)));
});
