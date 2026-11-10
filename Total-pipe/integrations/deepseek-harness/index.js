import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, isAbsolute, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

function defaultToolsEntry() {
  if (process.env.DSH_TOOLS_ENTRY) return process.env.DSH_TOOLS_ENTRY
  if (process.env.DSH_SOURCE) {
    return resolve(process.env.DSH_SOURCE, 'packages/core/tools/lib/index.js')
  }
  if (process.platform === 'win32') {
    const candidate = resolve(
      dirname(process.execPath),
      'resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-tools/lib/index.js',
    )
    if (existsSync(candidate)) return candidate
  }
  return ''
}

const DSH_TOOLS_ENTRY = defaultToolsEntry()
if (!DSH_TOOLS_ENTRY) {
  throw new Error('Set DSH_TOOLS_ENTRY or DSH_SOURCE so the plugin can load Harness tools')
}
const toolsSpecifier = isAbsolute(DSH_TOOLS_ENTRY)
  ? pathToFileURL(DSH_TOOLS_ENTRY).href
  : DSH_TOOLS_ENTRY
const { defineTool } = await import(toolsSpecifier)

export const name = 'totalpipe-dsh-plugin'
export const inject = ['tools']

const PROJECT_ROOT = process.env.TOTALPIPE_ROOT || fileURLToPath(new URL('../..', import.meta.url))
const BRIDGE_PATH = fileURLToPath(new URL('./bridge.py', import.meta.url))
const PYTHON = process.env.TOTALPIPE_PYTHON || (process.platform === 'win32' ? 'python' : 'python3')

function runBridge(payload) {
  return new Promise((resolve, reject) => {
    const child = spawn(PYTHON, [BRIDGE_PATH], {
      cwd: PROJECT_ROOT,
      env: { ...process.env, PYTHONUTF8: '1', PYTHONUNBUFFERED: '1' },
      stdio: ['pipe', 'pipe', 'pipe'],
    })
    let stdout = ''
    let stderr = ''
    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')
    child.stdout.on('data', (chunk) => {
      stdout += chunk
    })
    child.stderr.on('data', (chunk) => {
      stderr += chunk
    })
    child.once('error', reject)
    child.once('close', (code) => {
      if (code !== 0) {
        reject(new Error(stderr.trim() || 'Total-pipe bridge exited with code ' + code))
        return
      }
      try {
        resolve(JSON.parse(stdout))
      } catch (error) {
        reject(new Error('Total-pipe bridge returned invalid JSON: ' + error.message))
      }
    })
    child.stdin.end(JSON.stringify(payload))
  })
}

function renderJson(_args, value) {
  return [{ type: 'text', text: JSON.stringify(value, null, 2) }]
}

function outputSpec() {
  return {
    schema: { type: 'object', additionalProperties: true },
    render: renderJson,
  }
}

const STRING = { type: 'string' }
const OBJECT = { type: 'object', additionalProperties: true }
const ARRAY = { type: 'array', items: { type: 'string' } }

export function apply(ctx) {
  ctx.tools.register(defineTool({
    name: 'totalpipe_doctor',
    description: 'Check Total-pipe prerequisites and candidate/native capabilities without starting a job.',
    parameters: {
      deep: { type: 'boolean' },
      source_kind: { type: 'string' },
      page_mode: { type: 'string', enum: ['deck_ir', 'page_scene'] },
    },
    timeoutMs: 300000,
    output: outputSpec(),
    async execute(args) {
      return runBridge({ operation: 'doctor', arguments: args })
    },
  }))

  ctx.tools.register(defineTool({
    name: 'totalpipe_start',
    description: 'Start or resume a Total-pipe job from PDF, Markdown, workflow, or Deck IR. Does not choose a model implicitly.',
    parameters: {
      source: { ...STRING, required: true },
      out_dir: { ...STRING, required: true },
      language: { ...STRING, required: true },
      presentation_type: { ...STRING, required: true },
      source_kind: { type: 'string' },
      requirements: { type: 'string' },
      queries: { ...ARRAY },
      supplementary_paths: { ...ARRAY },
      supplementary_content_included: { type: 'boolean' },
      supplement: { type: 'string', enum: ['off', 'inline', 'pages', 'both'] },
      explain_viz_mode: { type: 'string', enum: ['auto', 'off', 'prefer'] },
      page_mode: { type: 'string', enum: ['deck_ir', 'page_scene'] },
      slide_count: { type: 'integer' },
    },
    timeoutMs: 1900000,
    output: outputSpec(),
    async execute(args) {
      return runBridge({ operation: 'start', arguments: args })
    },
  }))

  ctx.tools.register(defineTool({
    name: 'totalpipe_advance',
    description: 'Accept an explicit Total-pipe artifact or user input, then advance to the next decision or candidate. scene_preview renders selected PageScene pages without accepting them.',
    parameters: {
      job_id: { ...STRING, required: true },
      artifact_kind: { type: 'string' },
      artifact_path: { ...STRING },
      preflight: { type: 'boolean' },
      inputs: { ...OBJECT },
      replan_from: { type: 'string' },
      acknowledge: { ...OBJECT },
      preview: { ...OBJECT },
      scene_preview: { ...OBJECT },
      native: { ...OBJECT },
    },
    timeoutMs: 1900000,
    output: outputSpec(),
    async execute(args) {
      return runBridge({ operation: 'advance', arguments: args })
    },
  }))

  ctx.tools.register(defineTool({
    name: 'totalpipe_status',
    description: 'Read Total-pipe job state and QA without writes or running components.',
    parameters: {
      job_id: { ...STRING, required: true },
      detail: { type: 'string', enum: ['summary', 'full'] },
    },
    timeoutMs: 120000,
    output: outputSpec(),
    async execute(args) {
      return runBridge({ operation: 'status', arguments: args })
    },
  }))
}
