import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { defineTool } from process.env.DSH_TOOLS_ENTRY || '/home/simcrq/0_Project/dsh/packages/core/tools/lib/index.js'

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
    description: 'Run the complete PaperWorkflow literature-ingestion workflow for one project-local PDF or Markdown file. PDF input is converted with the configured MinerU OCR pipeline; Markdown input skips OCR. The tool builds raw E### chunks plus atomic S#### spans, localizes exact supporting passages, deduplicates them in an EV#### Evidence Registry, measures retrieval precision and workflow-facet coverage separately, and audits text capture, reading order, semantic headings, chunk coherence, supplementary dependencies, linked quantities and symbol definitions. It writes workflow.json, document.manifest.json and evidence.md. quality_audit means OCR/Markdown usability only; synthesis_readiness is hard-gated and must be used for scientific hand-off. Cite EV#### plus S####/E###, exact lines and character offsets for every major claim and number. Treat unavailable supplementary-dependent mechanisms as partial, separate laboratory and roll-to-roll conditions, and never merge differing values silently. The tool itself does not invent an LLM summary.',
    parameters: {
      source_path: {
        type: 'string',
        required: true,
        description: 'Project-local .pdf or .md path, absolute or relative to the PaperWorkflow project root.',
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
        description: 'Optional project-local artifact directory. Defaults to output/workflows/<source fingerprint>.',
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
    description: 'Index every PDF under PaperWorkflow/INput and generate a ready-to-use literature-workflow prompt from the user information. Call without selected_pdf first when the user has not chosen a paper: the result contains a deterministic numbered PDF index whose paths are all relative to INput. Present those choices and wait for the user selection. Call again with a selection_id such as P001 or an INput-relative path such as 4668/paper.pdf, plus any research goal, focus questions, and context. Never invent or expose an absolute path in the selection index.',
    parameters: {
      selected_pdf: {
        type: 'string',
        description: 'Optional selection_id from the returned index, or PDF path relative to INput. Omit to list all selectable PDFs.',
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
        selected_pdf: args.selected_pdf,
        research_goal: args.research_goal,
        focus_questions: args.focus_questions,
        additional_context: args.additional_context,
      })
    },
  }))
}
