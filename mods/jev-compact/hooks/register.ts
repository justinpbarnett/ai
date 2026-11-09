import type { EngineInterface, Register, SessionMessage } from 'claude-code'

const SWITCH_FLOOR_TOKENS = 90_000
const PAUSE_FLOOR_TOKENS = 120_000
const SURE = 0.8
const RECENT_CHARS = 12_000
const MESSAGE_CHARS = 2_000
const NEXT_TASK_CHARS = 500
const PAUSE_DELAY_MS = 2_000
const PEOPLE = new Set(['composer', 'bridge'])

const SWITCHES = 'Does the new message start a different task from the recent work, so that the details of the recent work no longer matter for it?'
const PAUSES = "Did the assistant's last reply finish the work the user asked for, with nothing left running and no question waiting on the user, so this is a good point to pause?"
const PAUSE_SUMMARY = 'The work just reached a good stopping point. Keep what was done and decided, the files touched, and anything the user may follow up on. Drop the working detail.'

let compacting = false
let compactedSinceAnswer = false
let submitted = 0

function clip(text: string, chars: number): string {
  const t = text.trim()
  return t.length <= chars ? t : `${t.slice(0, chars / 2)}\n[cut]\n${t.slice(-chars / 2)}`
}

function recent(messages: readonly SessionMessage[]): string {
  const lines: string[] = []
  let size = 0
  for (const m of [...messages].reverse()) {
    if (!m.text.trim()) continue
    const line = `[${m.role === 'user' ? 'user' : 'claude'}] ${clip(m.text, MESSAGE_CHARS)}`
    if (size + line.length > RECENT_CHARS) break
    lines.unshift(line)
    size += line.length
  }
  return lines.join('\n\n')
}

function nextTaskSummary(text: string): string {
  return 'The conversation is moving on to a new task. Summarize the finished work briefly: what was done and decided, '
    + 'the files changed, and anything left open. Keep in full only what bears on the next task, which begins: '
    + clip(text, NEXT_TASK_CHARS)
}

async function jevSure($: EngineInterface, question: string, text: string): Promise<string | undefined> {
  const ran = await $.process.run(['arete', 'ask', question, '--json'], { stdin: text, timeoutMs: 20_000 })
  if (ran.exitCode !== 0) {
    $.ui.log(`jev-compact: arete ask failed: ${(ran.stderr || ran.stdout).trim().slice(0, 200)}`, { to: 'debug' })
    return undefined
  }
  const reply = JSON.parse(ran.stdout) as { answer?: string; confidence?: number }
  return reply.answer === 'yes' && (reply.confidence ?? 0) >= SURE ? `JEV ${reply.confidence}` : undefined
}

async function contextTokens($: EngineInterface): Promise<number> {
  return (await $.session.usage()).context.tokens ?? 0
}

async function compact($: EngineInterface, tokens: number, why: string, instructions: string): Promise<void> {
  compacting = true
  try {
    const done = await $.session.compact({ instructions })
    if (done.skip !== undefined) return
    compactedSinceAnswer = true
    $.ui.toast(`jev-compact: compacted ${Math.round(tokens / 1000)}k tokens ${why}`)
  } catch (err) {
    $.ui.toast(`jev-compact: could not compact ${why}: ${String(err).slice(0, 160)}`)
  } finally {
    compacting = false
  }
}

async function compactIfSwitch($: EngineInterface, text: string): Promise<void> {
  if (compacting || compactedSinceAnswer) return
  const tokens = await contextTokens($)
  if (tokens < SWITCH_FLOOR_TOKENS) return
  const work = recent(await $.session.messages())
  if (!work) return
  const sure = await jevSure($, SWITCHES, `Recent work in this session:\n${work}\n\nNew message:\n${clip(text, MESSAGE_CHARS)}`)
  if (sure) await compact($, tokens, `before a new task (${sure})`, nextTaskSummary(text))
}

async function compactIfPause($: EngineInterface, mark: number): Promise<void> {
  if (compacting || compactedSinceAnswer || submitted !== mark) return
  const tokens = await contextTokens($)
  if (tokens < PAUSE_FLOOR_TOKENS) return
  const work = recent(await $.session.messages())
  if (!work) return
  const sure = await jevSure($, PAUSES, `Recent work in this session:\n${work}`)
  if (sure && submitted === mark) await compact($, tokens, `at a good stopping point (${sure})`, PAUSE_SUMMARY)
}

export const register: Register = on => {
  on('prompt.submit', async ($, e, next) => {
    submitted += 1
    if (e.command === undefined && e.isMeta === undefined && e.turnId === undefined && PEOPLE.has(e.origin.kind)) {
      await compactIfSwitch($, e.text).catch(err => $.ui.log(`jev-compact: ${err}`, { to: 'debug' }))
    }
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const done = await next(e)
    if (e.agentId === undefined && e.reason === 'answer') {
      compactedSinceAnswer = false
      if (e.answer.trim()) {
        const mark = submitted
        $.clock.after(PAUSE_DELAY_MS, () => {
          compactIfPause($, mark).catch(err => $.ui.log(`jev-compact: ${err}`, { to: 'debug' }))
        })
      }
    }
    return done
  })

  on('session.compact', async ($, e, next) => {
    const done = await next(e)
    if (e.agentId === undefined && e.trigger !== 'precompute' && done.skip === undefined) compactedSinceAnswer = true
    return done
  })
}
