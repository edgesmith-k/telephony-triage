// tt-guard.js — telephony-triage guard plugin for OpenCode 1.19.5 (plan I, option A: analysis-only v1).
//
// Every tool call goes through `plugin/scripts/common/oc_adapter.py before`, which maps the OpenCode call to the
// Claude Code PreToolUse hook JSON and runs the unchanged guard.py (as hooks.json does). MCP results go through
// `oc_adapter.py after`, which runs the unchanged jira_bridge.py (PostToolUse) and replaces the content.
// 1.19.5 runs no `tool.execute.after` for an MCP call that ends in an error (MCP isError, JSON-RPC error, timeout): the
// error text (= the response body) would reach the model as is. `experimental.chat.messages.transform` runs before every
// model request (compaction included) on the messages about to be sent; there every error tool part of a non-built-in tool
// goes through `oc_adapter.py error`, which hides a Jira error body ("Jira 오류(본문 숨김): <tool> <class>"). Only the
// request is changed — the stored session keeps the original (the terminal output shows it to the user).
//
// Fail-closed: a spawn error, a signal, a timeout, a non-zero exit, or output that is not a decision blocks the call
// (before) or replaces the result with an error string (after). guard stderr goes to a log; the first warning in a
// session blocks that one call so the model sees it. `node:` imports only — no package.json, no node_modules.
//
// Env: TT_PLUGIN_ROOT (plugin root; default: the path `tools/gen_opencode.py install` writes into INSTALLED_ROOT,
//      else <this file>/../../plugin for the repo or bundle layout), TT_PYTHON (default python3),
//      TT_OC_GUARD_LOG (default $XDG_STATE_HOME/telephony-triage/oc-guard.log),
//      TT_OC_TEST_TIMEOUT_MS (tests only: can only shorten the timeouts).
//      TT_OC_JIRA_SESSION_GATE is set by this file (the Jira read gate decided at load), never read from the env.
import { spawn } from "node:child_process"
import { appendFileSync, existsSync, mkdirSync } from "node:fs"
import { homedir } from "node:os"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const HERE = dirname(fileURLToPath(import.meta.url))
// `gen_opencode.py install` copies this file to <dest>/.opencode/plugins/ (auto-loaded by 1.19.5) and replaces the
// placeholder below with --plugin-root. Left as is (repo or bundle copy), it is ignored.
const INSTALLED_ROOT = "@@PLUGIN_ROOT@@"
const INSTALLED = INSTALLED_ROOT.startsWith("@" + "@") ? "" : INSTALLED_ROOT
const ROOT = resolve(process.env.TT_PLUGIN_ROOT || INSTALLED || join(HERE, "..", "..", "plugin"))
const ADAPTER = join(ROOT, "scripts", "common", "oc_adapter.py")
const PYTHON = process.env.TT_PYTHON || "python3"
const STATE = process.env.XDG_STATE_HOME || join(homedir(), ".local", "state")
const LOG = process.env.TT_OC_GUARD_LOG || join(STATE, "telephony-triage", "oc-guard.log")
const MARGIN_MS = 15000
// hooks.json timeouts: Bash 180 s, MCP and file tools 30 s. The adapter keeps to them; the margin covers startup.
const TIMEOUT_MS = { bash: 180000 + MARGIN_MS, default: 30000 + MARGIN_MS, after: 30000 + MARGIN_MS }
// Built-in tools of 1.19.5 (same table as oc_adapter.BUILTINS); only used to skip the after hook.
const BUILTINS = new Set(["invalid", "question", "read", "glob", "grep", "skill", "lsp", "todowrite", "bash", "edit",
  "write", "apply_patch", "task", "webfetch", "websearch", "codesearch", "execute", "plan", "list_mcp_resources",
  "list_mcp_resource_templates", "read_mcp_resource"])
const BRIDGE_FAILED = "telephony-triage: OpenCode jira_bridge 처리 실패 — 원문은 표시하지 않는다. " +
  "Claude Code에서 다시 읽거나 config.py doctor로 확인한다."
const ERROR_HIDDEN = "Jira 오류(본문 숨김)"   // = oc_adapter.JIRA_ERROR_HIDDEN

function timeoutFor(kind) {
  const ms = TIMEOUT_MS[kind] ?? TIMEOUT_MS.default
  const test = Number(process.env.TT_OC_TEST_TIMEOUT_MS)
  return Number.isFinite(test) && test > 0 ? Math.min(ms, test) : ms
}

function log(entry) {
  try {
    mkdirSync(dirname(LOG), { recursive: true })
    appendFileSync(LOG, JSON.stringify({ t: new Date().toISOString(), ...entry }) + "\n")
  } catch {
    // logging must never decide anything
  }
}

// Jira read gate (oc_adapter `gate`): decided once when the plugin loads, from the user config and the in-house check
// record, then passed to every adapter call as JIRA_SESSION_ENV. A config or record written during the session (by
// anyone, the model included) does not apply until OpenCode starts again. Unknown or failed → "closed".
const JIRA_SESSION_ENV = "TT_OC_JIRA_SESSION_GATE"   // = oc_adapter.JIRA_SESSION_ENV
let jiraSessionGate = "closed"

function adapterEnv() {
  return { ...process.env, [JIRA_SESSION_ENV]: jiraSessionGate }
}

function runAdapter(mode, payload, timeoutMs) {
  return new Promise((done) => {
    const res = { status: null, signal: null, stdout: "", stderr: "", error: null, timedOut: false }
    let child
    try {
      child = spawn(PYTHON, [ADAPTER, mode], { stdio: ["pipe", "pipe", "pipe"], env: adapterEnv() })
    } catch (err) {
      res.error = String(err)
      return done(res)
    }
    const timer = setTimeout(() => {
      res.timedOut = true
      try { child.kill("SIGKILL") } catch { /* already gone */ }
    }, timeoutMs)
    child.stdout.setEncoding("utf8")
    child.stderr.setEncoding("utf8")
    child.stdout.on("data", (d) => { res.stdout += d })
    child.stderr.on("data", (d) => { res.stderr += d })
    child.stdin.on("error", () => { /* EPIPE: the exit status decides */ })
    child.on("error", (err) => { res.error = String(err) })
    child.on("close", (status, signal) => {
      clearTimeout(timer)
      res.status = status
      res.signal = signal
      done(res)
    })
    try {
      child.stdin.end(JSON.stringify(payload))
    } catch (err) {
      res.error = String(err)
    }
  })
}

function failure(r) {
  if (r.error) return `adapter spawn failed (${r.error})`
  if (r.timedOut) return "adapter timed out"
  if (r.signal) return `adapter killed by ${r.signal}`
  if (r.status !== 0) return `adapter exit status ${r.status}`
  return null
}

// Every block message starts with MARK so `tt-oc` can tell a block from an ordinary tool error (exit code 3).
const MARK = "[telephony-triage]"
function marked(reason) {
  return reason.startsWith(MARK) ? reason : `${MARK} ${reason}`
}

function parseJson(text) {
  try {
    const v = JSON.parse(text)
    return v && typeof v === "object" && !Array.isArray(v) ? v : null
  } catch {
    return null
  }
}

export const TtGuard = async ({ directory }) => {
  const warned = new Set()
  const argsByCall = new Map()   // callID -> args, for the after hook (its input may not carry args)
  const allowedCalls = new Set() // non-built-in calls the before hook allowed (an error part of one is not our block text)
  const errorText = new Map()    // callID + error text -> replacement (string) or null (keep), for the transform hook
  let model = process.env.TT_MODEL || ""
  const missing = existsSync(ADAPTER) ? null : `[telephony-triage] tt-guard: ${ADAPTER} not found — every tool is denied`
  if (missing) log({ hook: "init", error: missing })
  if (!missing) {
    const r = await runAdapter("gate", {}, timeoutFor("default"))
    const fail = failure(r)
    const d = fail ? null : parseJson(r.stdout)
    jiraSessionGate = d && d.open === true ? "open" : "closed"
    log({ hook: "gate", jira: jiraSessionGate, fail, problems: Array.isArray(d?.problems) ? d.problems : undefined })
  }

  return {
    "tool.execute.before": async (input, output) => {
      if (missing) throw new Error(missing)
      const tool = String(input?.tool ?? "")
      const payload = { tool, args: output?.args ?? {}, directory, sessionID: input?.sessionID, callID: input?.callID }
      const r = await runAdapter("before", payload, timeoutFor(tool === "bash" ? "bash" : "default"))
      const fail = failure(r)
      const d = fail ? null : parseJson(r.stdout)
      const warnings = Array.isArray(d?.warnings) ? d.warnings.map(String) : []
      log({ hook: "before", tool, session: input?.sessionID, decision: d?.decision ?? null, fail,
        reason: d?.reason ? String(d.reason).slice(0, 500) : undefined, events: d?.events, warnings,
        stderr: r.stderr ? r.stderr.slice(0, 2000) : undefined })
      if (fail) throw new Error(`[telephony-triage] tt-guard blocked ${tool}: ${fail}`)
      if (!d) throw new Error(`[telephony-triage] tt-guard blocked ${tool}: adapter output is not a decision`)
      if (d.decision !== "allow") throw new Error(marked(String(d.reason || `tt-guard blocked ${tool}`)))
      if (input?.callID && !BUILTINS.has(tool)) {
        argsByCall.set(input.callID, payload.args)
        allowedCalls.add(input.callID)
      }
      const session = String(input?.sessionID ?? "")
      if (warnings.length && !warned.has(session)) {
        warned.add(session)
        throw new Error("[telephony-triage] guard warning (shown once per session; read it, then retry the same call):\n" +
          warnings.join("\n"))
      }
    },

    "tool.execute.after": async (input, output) => {
      const tool = String(input?.tool ?? "")
      if (BUILTINS.has(tool) || !output) return
      const args = input?.args ?? argsByCall.get(input?.callID) ?? {}
      argsByCall.delete(input?.callID)
      const replace = (text) => {
        output.content = [{ type: "text", text }]
        if (typeof output.output === "string") output.output = text
      }
      if (missing) return replace(BRIDGE_FAILED)
      const payload = { tool, args, directory, sessionID: input?.sessionID, callID: input?.callID,
        content: output.content }
      const r = await runAdapter("after", payload, timeoutFor("after"))
      const fail = failure(r)
      const d = fail ? null : parseJson(r.stdout)
      log({ hook: "after", tool, session: input?.sessionID, fail, replaced: d ? d.replace !== null : null,
        stderr: r.stderr ? r.stderr.slice(0, 2000) : undefined })
      if (fail || !d || !("replace" in d)) return replace(BRIDGE_FAILED)
      if (typeof d.replace === "string") return replace(d.replace)
      if (d.replace !== null) return replace(BRIDGE_FAILED)
    },

    "experimental.chat.messages.transform": async (_input, output) => {
      const parts = []
      for (const m of Array.isArray(output?.messages) ? output.messages : []) {
        for (const p of Array.isArray(m?.parts) ? m.parts : []) {
          if (p?.type === "tool" && p?.state?.status === "error" && !BUILTINS.has(String(p.tool ?? ""))) {
            parts.push({ p, sessionID: m?.info?.sessionID })
          }
        }
      }
      for (const { p, sessionID } of parts) {
        const tool = String(p.tool ?? "")
        const text = String(p.state.error ?? "")
        const key = `${p.callID}\u0000${text}`
        try {
          if (!errorText.has(key)) {
            let rep
            if (missing) {
              rep = `${ERROR_HIDDEN}: ${tool} tt-guard`
            } else {
              const payload = { tool, args: p.state.input ?? {}, directory, sessionID, callID: p.callID, error: text,
                allowed: allowedCalls.has(p.callID) }
              const r = await runAdapter("error", payload, timeoutFor("after"))
              const fail = failure(r)
              const d = fail ? null : parseJson(r.stdout)
              log({ hook: "error", tool, session: sessionID, fail, replaced: d ? d.replace !== null : null,
                stderr: r.stderr ? r.stderr.slice(0, 2000) : undefined })
              if (fail || !d || !("replace" in d)) rep = `${ERROR_HIDDEN}: ${tool} tt-guard`
              else if (d.replace === null) rep = null
              else rep = typeof d.replace === "string" ? d.replace : `${ERROR_HIDDEN}: ${tool} tt-guard`
            }
            errorText.set(key, rep)
          }
          const rep = errorText.get(key)
          if (typeof rep === "string") p.state.error = rep
        } catch {
          p.state.error = `${ERROR_HIDDEN}: ${tool} tt-guard`   // fail closed: never send a body we could not judge
        }
      }
    },

    "shell.env": async (_input, output) => {
      if (!output || typeof output.env !== "object") return
      output.env.TT_RUNTIME = "opencode"
      output.env.CLAUDE_PLUGIN_ROOT = ROOT
      output.env[JIRA_SESSION_ENV] = jiraSessionGate   // shown by config.py doctor only; the adapter never reads bash env
      if (model) output.env.TT_MODEL = model
      // The git settings tt-oc put in this process env (GIT_SAFE: safe.bareRepository=explicit, protocol.ext.allow=never)
      // are set again for the bash child as they are. `git -c` values from the env are cleared (an empty
      // GIT_CONFIG_PARAMETERS is accepted by git). GIT_ALLOW_PROTOCOL is not touched here: empty means "no protocol" to git;
      // tt-oc removes it from the env instead.
      const count = process.env.GIT_CONFIG_COUNT
      if (count !== undefined) {
        output.env.GIT_CONFIG_COUNT = count
        for (let i = 0; i < (/^[0-9]{1,4}$/.test(count) ? Number(count) : 0); i++) {
          for (const part of ["KEY", "VALUE"]) {
            const name = `GIT_CONFIG_${part}_${i}`
            if (process.env[name] !== undefined) output.env[name] = process.env[name]
          }
        }
      }
      output.env.GIT_CONFIG_PARAMETERS = ""
    },

    "chat.params": async (input) => {
      try {
        const id = input?.model?.id
        const provider = input?.model?.providerID ?? input?.provider?.info?.id
        if (id && !process.env.TT_MODEL) model = provider ? `${provider}/${id}` : String(id)
      } catch {
        // provenance only
      }
    },
  }
}
