import { spawn } from 'node:child_process'
import { isAbsolute, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const DSH_TOOLS_ENTRY = process.env.DSH_TOOLS_ENTRY
  || (process.env.DSH_SOURCE
    ? resolve(process.env.DSH_SOURCE, 'packages/core/tools/lib/index.js')
    : '')
if (!DSH_TOOLS_ENTRY) {
  throw new Error('Set DSH_TOOLS_ENTRY or DSH_SOURCE so the plugin can load Harness tools')
}
const toolsSpecifier = isAbsolute(DSH_TOOLS_ENTRY)
  ? pathToFileURL(DSH_TOOLS_ENTRY).href
  : DSH_TOOLS_ENTRY
const { defineTool } = await import(toolsSpecifier)

export const name = 'paperworkflow-dsh-plugin'
export const inject = ['tools']

// The PaperWorkflow project root is derived from this plugin's own location
// (integrations/deepseek-harness -> project root) and can be overridden with
// PAPERWORKFLOW_ROOT when the plugin is installed from a different checkout.
const PROJECT_ROOT = process.env.PAPERWORKFLOW_ROOT || fileURLToPath(new URL('../..', import.meta.url))
const BRIDGE_PATH = fileURLToPath(new URL('./bridge.py', import.meta.url))
const PYTHON = process.env.PAPERWORKFLOW_PYTHON || 'python3'

function runBridge(payload) {
  return new Promise((resolve, reject) => {
    const child = spawn(PYTHON, [BRIDGE_PATH], {
      cwd: PROJECT_ROOT,
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
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
        reject(new Error(stderr.trim() || 'PaperWorkflow bridge exited with code ' + code))
        return
      }
      try {
        resolve(JSON.parse(stdout))
      } catch (error) {
        reject(new Error('PaperWorkflow bridge returned invalid JSON: ' + error.message))
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

export function apply(ctx) {
  ctx.tools.register(defineTool({
    name: 'paperworkflow_literature_workflow',
    description: 'Run PaperWorkflow stage 1 for any local PDF or Markdown file. PDF input uses the configured MinerU OCR pipeline; Markdown input skips OCR. The tool emits one self-contained Total-pipe bundle containing workflow.json, document.manifest.json, evidence.md, paper.md, extracted figure assets, and bundle.manifest.json. synthesis_readiness is the scientific hand-off gate. Cite EV#### plus S####/E### and exact offsets for major claims.',
    parameters: {
      source_path: {
        type: 'string',
        required: true,
        description: 'Any readable local .pdf or .md path.',
      },
      queries: {
        type: 'array',
        items: { type: 'string' },
        description: 'Optional research questions in Chinese or English. Recognized scientific intents are expanded bilingually and reranked by relevant paper sections. Default queries for objectives, methods, results, and limitations are also included unless include_default_queries is false.',
      },
      include_default_queries: {
        type: 'boolean',
        description: 'Include built-in bilingual evidence queries. Defaults to true.',
      },
      top_k: {
        type: 'integer',
        description: 'Base number of ranked evidence passages per query, from 1 to 20. Coverage-sensitive intents may add passages needed to audit workflow facets. Defaults to 5.',
      },
      chunk_chars: {
        type: 'integer',
        description: 'Maximum characters per addressable evidence chunk, from 500 to 20000. Defaults to 6000.',
      },
      output_dir: {
        type: 'string',
        description: 'Optional local bundle directory, including outside the project. Defaults to output/workflows/<source fingerprint>.',
      },
    },
    timeoutMs: 1900000,
    output: outputSpec(),
    async execute(args) {
      return runBridge({
        operation: 'literature_workflow',
        source_path: args.source_path,
        queries: args.queries ?? [],
        include_default_queries: args.include_default_queries ?? true,
        top_k: args.top_k ?? 5,
        chunk_chars: args.chunk_chars ?? 6000,
        output_dir: args.output_dir,
      })
    },
  }))

  ctx.tools.register(defineTool({
    name: 'paperworkflow_prompt_builder',
    description: 'Index PDFs under any source_dir and generate a ready-to-use literature-workflow prompt. source_dir defaults to the legacy INput folder. Call without selected_pdf to list deterministic P001-style choices, then call again with the chosen id or relative path.',
    parameters: {
      source_dir: {
        type: 'string',
        description: 'Any local directory to index recursively. Defaults to PaperWorkflow/INput.',
      },
      selected_pdf: {
        type: 'string',
        description: 'Optional selection_id or source_dir-relative PDF path. Omit to list all PDFs.',
      },
      research_goal: {
        type: 'string',
        description: 'Optional research objective. A literature-analysis default is used when omitted.',
      },
      focus_questions: {
        type: 'array',
        items: { type: 'string' },
        description: 'Optional questions the generated prompt must answer. Defaults cover preparation, measurement, physical picture, results, and limitations.',
      },
      additional_context: {
        type: 'string',
        description: 'Optional background, domain, audience, comparison target, or special constraint to include in the prompt.',
      },
    },
    timeoutMs: 30000,
    output: outputSpec(),
    async execute(args) {
      return runBridge({
        operation: 'prompt_builder',
        source_dir: args.source_dir,
        selected_pdf: args.selected_pdf,
        research_goal: args.research_goal,
        focus_questions: args.focus_questions,
        additional_context: args.additional_context,
      })
    },
  }))
}
