import test from 'node:test';
import assert from 'node:assert/strict';
import { compileSlideDesignIR } from '../server/design-intelligence/design-compiler.mjs';
import { evaluateVisualQuality } from '../server/visual-quality/index.mjs';
import { adaptArtifactToolTelemetry } from '../server/renderer-adapters/artifact-tool.mjs';
import { assertJsonSchema } from '../server/schema-validator.mjs';
import fs from 'node:fs';

const intent = { objective: '定量证据仅覆盖特定样品', required_on_screen: ['2 nm MoS₂'], emphasis: 'low', speaker_notes: ['补充实验有其他材料'], appendix: ['完整 Raman 数据'] };
function telemetry(content) {
  return adaptArtifactToolTelemetry({schema:'openai.presentation.layout/v4', slide:{aid:'sl/1',frame:{width:1280,height:720}},elements:[{
    aid:'sh/1',kind:'shape',name:'body',text:content,bbox:[50,100,700,300],resolvedFontSize:24,
    resolvedTextStyle:{color:'#000000'},textLayout:{lineCount:1,overflow:false},
  }]});
}
test('intent is optional, validated, preserved and controls primary message/emphasis',()=>{
  assert.equal(compileSlideDesignIR({title:'Legacy'}).presentation_intent,undefined);
  const ir=compileSlideDesignIR({title:'Scope',metadata:{presentation_intent:intent}});
  assert.equal(ir.message.primary,intent.objective);
  assert.equal(ir.design_intent.accent_strength,'low');
  assert.deepEqual(ir.presentation_intent.speaker_notes,intent.speaker_notes);
  assertJsonSchema(JSON.parse(fs.readFileSync(new URL('../schemas/slide-design-ir.schema.json',import.meta.url),'utf8')),ir);
  assert.throws(()=>compileSlideDesignIR({metadata:{presentation_intent:{objective:''}}}),TypeError);
});
test('QA checks literal required text, not notes or semantic equivalence',async()=>{
  const ir=compileSlideDesignIR({metadata:{presentation_intent:intent}});
  const missing=await evaluateVisualQuality({telemetry:telemetry('扩展到其他材料'),design_ir:ir});
  assert.equal(missing.checks.presentation_intent.status,'fail');
  assert.ok(missing.violations.some(v=>v.code==='REQUIRED_ON_SCREEN_MISSING'));
  const pass=await evaluateVisualQuality({telemetry:telemetry('2 nm\nMoS₂ 样品'),design_ir:ir});
  assert.equal(pass.checks.presentation_intent.status,'pass');
  const noIntent=await evaluateVisualQuality({telemetry:telemetry('旧页面')});
  assert.equal(noIntent.checks.presentation_intent,undefined);
});
