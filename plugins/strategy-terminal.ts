/**
 * Strategy Terminal plugin for OpenCode.
 *
 * Drives the StrategyTerminal command engine (`app-cli.py`) headlessly and
 * exposes it as tools:
 *
 *   st.run       – run one terminal command ("AAPL", "AAPL GP 1y", "WEI", …)
 *   st.commands  – list every available command
 *
 * Anonymous by default, so no user id or password is required.
 *
 * No credentials are stored in this file.  API keys are read by app-cli.py
 * itself, from the app's own user store or from environment variables
 * (FRED_API_KEY, FMP_API_KEY, POLYGON_API_KEY, NEWSAPI_KEY, …).
 *
 * This build loads local plugins through two different shapes depending on the
 * entry point, so the default export provides both:
 *   • `setup(ctx)`  – the tool-transform style loader (`id` + `setup`)
 *   • `server()`    – the legacy `{ server() }` loader (tools via hooks)
 *
 * Configuration (all optional, see README):
 *   ST_CLI_APP_DIR     folder containing app-cli.py
 *                      (default: the bundled app at
 *                       ~/.config/opencode/strategy-terminal, installed by
 *                       install.sh; falls back to ~/Apps/StrategyTerminal)
 *   ST_CLI_PYTHON      python interpreter with the app's dependencies
 *                      (default: <app>/venv/bin/python, ~/venv/bin/python, python3)
 *   ST_CLI_SCRIPT      default app-cli.py
 *   ST_CLI_TIMEOUT_MS  default 240000
 */
import { spawn } from "node:child_process"
import { existsSync } from "node:fs"
import { homedir } from "node:os"
import path from "node:path"

const OPENCODE_DIR = process.env.OPENCODE_CONFIG_DIR ?? path.join(homedir(), ".config", "opencode")
const BUNDLED_APP_DIR = path.join(OPENCODE_DIR, "strategy-terminal")
const LEGACY_APP_DIR = path.join(homedir(), "Apps", "StrategyTerminal")

/** App folder: env override, else the bundled copy, else the legacy app folder. */
function resolveAppDir(): string {
  if (process.env.ST_CLI_APP_DIR) return process.env.ST_CLI_APP_DIR
  if (existsSync(path.join(BUNDLED_APP_DIR, "app-cli.py"))) return BUNDLED_APP_DIR
  return LEGACY_APP_DIR
}

const APP_DIR = resolveAppDir()
const SCRIPT = process.env.ST_CLI_SCRIPT ?? "app-cli.py"
const TIMEOUT_MS = Number(process.env.ST_CLI_TIMEOUT_MS ?? 240_000)
const MAX_OUTPUT = 200_000

/** First existing candidate wins; the last entry is always returned as-is. */
function firstExisting(candidates: string[]): string {
  for (const candidate of candidates.slice(0, -1)) {
    try {
      if (existsSync(candidate)) return candidate
    } catch {
      /* keep looking */
    }
  }
  return candidates[candidates.length - 1]
}

/** Python interpreter to drive the CLI with. */
function resolvePython(): string {
  if (process.env.ST_CLI_PYTHON) return process.env.ST_CLI_PYTHON
  const venvs = [
    path.join(APP_DIR, "venv", "bin", "python"),
    path.join(APP_DIR, ".venv", "bin", "python"),
    path.join(homedir(), "venv", "bin", "python"),
  ]
  return firstExisting([...venvs, "python3"])
}

type RunInput = {
  command: string
  user?: string
  images?: boolean
  show?: boolean
  open_pdf?: boolean
  max_rows?: number
}

type ToolOutput = { text: string; images: string[]; code: number }

const RUN_DESCRIPTION =
  "Run a Strategy Terminal command. Examples: \"AAPL\" (overview), \"AAPL GP 6mo\" " +
  "(price chart), \"AAPL FA\"/\"AAPL NEWS\"/\"AAPL OPT\"/\"AAPL DVD\", \"AAPL COMP MSFT AMD\", " +
  "\"WEI\" (world indices), \"MOVERS gainers\", \"FX\", \"CRYPTO\", \"CRYPTO TOP\", " +
  "\"COIN bitcoin\", \"RATES\", \"CMDTY\", \"SECTOR\", \"ECON\", \"ECON GLOBAL\", " +
  "\"NEWS\"/\"NEWS TECH\"/\"NEWS fed\"/\"NEWS FEED\"/\"NEWS SENTIMENT\", \"SENTIMENT AAPL\", " +
  "\"IND SPX\", \"WB\", \"OAS HY\", \"OASD 1-3Y\", \"VOL TSLA 6mo\", \"IV AAPL\", " +
  "\"RISK NVDA\", \"TRA AAPL SPY 5y\", \"ANR AAPL\", \"RV AAPL\", \"SHORT AAPL\", " +
  "\"INSIDER AAPL\", \"IPO\", \"TOP\", \"ECAL\", \"SCREEN\", \"SEARCH apple\", " +
  "\"WL\"/\"PNL\"/\"PORT\"/\"LIST ALERT\" (need `user`), \"HELP\". " +
  "Runs anonymously unless `user` is given. Chart images come back with the result."

const COMMANDS_DESCRIPTION =
  "List every command supported by the Strategy Terminal (ticker, market, macro, news, " +
  "analysis, watchlist, P&L and alert commands)."

/** Run app-cli.py with the given arguments. Never rejects. */
function runCli(
  args: string[],
  signal?: AbortSignal,
): Promise<{ code: number; stdout: string; stderr: string; note?: string }> {
  return new Promise((resolve) => {
    const script = path.join(APP_DIR, SCRIPT)
    if (!existsSync(script)) {
      resolve({
        code: -1,
        stdout: "",
        stderr:
          `${SCRIPT} not found in ${APP_DIR}.\n` +
          "Set ST_CLI_APP_DIR to the folder that contains app-cli.py.",
      })
      return
    }

    let child
    try {
      child = spawn(resolvePython(), [SCRIPT, ...args], {
        cwd: APP_DIR,
        env: { ...process.env, PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8" },
      })
    } catch (error) {
      resolve({ code: -1, stdout: "", stderr: `failed to start python: ${error}` })
      return
    }

    let stdout = ""
    let stderr = ""
    let note: string | undefined
    const done = (code: number) => resolve({ code, stdout, stderr, note })

    const timer = setTimeout(() => {
      note = `timed out after ${Math.round(TIMEOUT_MS / 1000)}s — process killed`
      child.kill("SIGKILL")
    }, TIMEOUT_MS)

    const onAbort = () => child.kill("SIGKILL")
    signal?.addEventListener("abort", onAbort, { once: true })

    child.stdout?.on("data", (chunk: Buffer) => {
      if (stdout.length < MAX_OUTPUT) stdout += chunk.toString("utf8")
    })
    child.stderr?.on("data", (chunk: Buffer) => {
      if (stderr.length < MAX_OUTPUT) stderr += chunk.toString("utf8")
    })
    child.on("error", (error) => {
      clearTimeout(timer)
      signal?.removeEventListener("abort", onAbort)
      stderr += `\n${error}`
      done(-1)
    })
    child.on("close", (code) => {
      clearTimeout(timer)
      signal?.removeEventListener("abort", onAbort)
      done(code ?? -1)
    })
  })
}

/** Absolute PNG paths the CLI printed as markdown image links. */
function chartImages(stdout: string): string[] {
  const found = new Set<string>()
  const pattern = /!\[[^\]]*\]\(([^)]+\.png)\)/g
  let match: RegExpExecArray | null
  while ((match = pattern.exec(stdout)) !== null) {
    const file = match[1].trim()
    if (file.startsWith("/")) found.add(file)
  }
  return [...found]
}

/** Pull `--show` / PDF viewer flags out of the command text. */
function splitShowFlags(command: string): {
  command: string
  show?: boolean
  openPdf?: boolean
} {
  let show: boolean | undefined
  let openPdf: boolean | undefined
  const kept: string[] = []

  for (const token of command.trim().split(/\s+/)) {
    if (!token) continue
    if (token === "--show") {
      show = true
    } else if (token === "--open-pdf") {
      show = true
      openPdf = true
    } else if (token === "--no-open-pdf") {
      openPdf = false
    } else {
      kept.push(token)
    }
  }

  return { command: kept.join(" "), show, openPdf }
}

/** CLI arguments for one terminal command. */
function buildArgs(input: RunInput): string[] {
  const args: string[] = []
  const parsed = splitShowFlags(input.command)
  const command = parsed.command || input.command.trim()
  const show = input.show ?? parsed.show ?? false
  const openPdf = input.open_pdf ?? parsed.openPdf ?? true

  if (input.user) {
    const who = input.user.trim()
    args.push(/^\d+$/.test(who) ? "--user-id" : "--email", who)
  } else {
    args.push("--anonymous")
  }

  args.push("--no-save-data")
  if (input.images === false) args.push("--no-images")
  if (input.max_rows) args.push("--max-rows", String(input.max_rows))
  // `--show` renders the report, opens it in the browser, and returns its
  // pages as images. `open_pdf: false` keeps the PDF on disk instead.
  if (show) {
    args.push("--pdf", openPdf ? "--open-pdf" : "--no-open-pdf", "--pdf-png")
  }
  args.push(command)
  return args
}

/** Shared implementation used by both plugin shapes. */
async function runCommand(input: RunInput, signal?: AbortSignal): Promise<ToolOutput> {
  const command = String(input.command ?? "").trim()
  if (!command) {
    return { text: 'No command given. Try "HELP" for the command reference.', images: [], code: 2 }
  }

  const result = await runCli(buildArgs({ ...input, command }), signal)
  const images = chartImages(result.stdout)
  const text = [
    result.stdout.trim(),
    result.stderr.trim() ? `\n[stderr]\n${result.stderr.trim()}` : "",
    result.note ? `\n[note] ${result.note}` : "",
    result.code !== 0 ? `\n[exit ${result.code}]` : "",
    images.length
      ? `\n[charts] ${images.length} PNG(s):\n` + images.map((f) => `  ${f}`).join("\n")
      : "",
  ]
    .filter(Boolean)
    .join("\n")

  return { text: text || "(no output)", images, code: result.code }
}

async function listCommands(signal?: AbortSignal): Promise<string> {
  const result = await runCli(["--list-commands"], signal)
  return result.stdout.trim() || result.stderr.trim() || "(no output)"
}

/* ────────────────────────────────  V2 loader  ─────────────────────────────── */

const RUN_INPUT_SCHEMA = {
  type: "object" as const,
  properties: {
    command: {
      type: "string",
      description:
        'Terminal command, e.g. "AAPL", "AAPL GP 1y", "WEI", "VOL TSLA 6mo", "NEWS TOP", "RATES".',
    },
    user: {
      type: "string",
      description:
        "Act as this user: a numeric id or an e-mail. Omit to run anonymously (default).",
    },
    images: { type: "boolean", description: "Export charts as PNG images (default true)." },
    show: {
      type: "boolean",
      description:
        "Render a report of this output, open the PDF in the browser and return its pages " +
        "as images to show inline. May also be passed as `--show` in the command (default false).",
    },
    open_pdf: {
      type: "boolean",
      description:
        "When show is true, open the report in the browser (default true; set false to keep " +
        "the PDF on disk).",
    },
    max_rows: { type: "number", description: "Maximum table rows to render (default 60)." },
  },
  required: ["command"],
  additionalProperties: false,
}

async function setupV2(ctx: any) {
  await ctx.tool.transform((editor: any) => {
    editor.namespace({
      name: "st",
      description:
        "Strategy Terminal — market data, technicals, macro, news, portfolio and risk " +
        "commands from the StrategyTerminal app (anonymous by default).",
    })

    editor.add({
      name: "run",
      description: RUN_DESCRIPTION,
      input: RUN_INPUT_SCHEMA,
      options: { namespace: "st", codemode: true },
      async execute(input: RunInput, context: any) {
        await context?.progress?.({ status: `st: ${input.command}` })
        const { text, images } = await runCommand(input, context?.signal)
        return {
          content: [
            { type: "text" as const, text },
            ...images.slice(0, 8).map((file) => ({
              type: "file" as const,
              uri: `file://${file}`,
              mime: "image/png",
              name: path.basename(file),
            })),
          ],
        }
      },
    })

    editor.add({
      name: "commands",
      description: COMMANDS_DESCRIPTION,
      input: { type: "object", properties: {}, additionalProperties: false },
      options: { namespace: "st", codemode: true },
      async execute(_input: unknown, context: any) {
        return { content: await listCommands(context?.signal) }
      },
    })
  })
}

/* ────────────────────────────────  V1 loader  ─────────────────────────────── */

async function serverV1() {
  // Imported lazily so the other loader never has to resolve this package.
  const { tool } = await import("@opencode-ai/plugin")

  return {
    tool: {
      strategy_terminal: tool({
        description: RUN_DESCRIPTION,
        args: {
          command: tool.schema.string().describe('Terminal command, e.g. "AAPL GP 1y", "WEI"'),
          user: tool.schema
            .string()
            .optional()
            .describe("Numeric user id or e-mail; omit to run anonymously"),
          show: tool.schema
            .boolean()
            .optional()
            .describe(
              "Render a report, open the PDF in the browser and return its pages as images " +
                "(default false). May also be passed as `--show` in the command.",
            ),
          open_pdf: tool.schema
            .boolean()
            .optional()
            .describe(
              "When show is true, open the report in the browser (default true; set false to " +
                "keep the PDF on disk)",
            ),
        },
        async execute(args: RunInput) {
          const { text, images } = await runCommand(args)
          return {
            title: `strategy_terminal: ${args.command}`,
            output: text,
            metadata: { command: args.command, images },
            attachments: images.slice(0, 8).map((file) => ({
              type: "file" as const,
              mime: "image/png",
              url: `file://${file}`,
              filename: path.basename(file),
            })),
          }
        },
      }),
      strategy_terminal_commands: tool({
        description: COMMANDS_DESCRIPTION,
        args: {},
        async execute() {
          return listCommands()
        },
      }),
    },
  }
}

/* ────────────────────────────────  Export  ────────────────────────────────── */

export default {
  id: "strategy-terminal",
  setup: setupV2,
  server: serverV1,
}
