import type { EngineInterface, Register, SessionMessage } from 'claude-code'

const SWITCH_FLOOR_TOKENS = 90_000
const PAUSE_FLOOR_TOKENS = 120_000
const SURE = 0.8
const RECENT_CHARS = 12_000
const MESSAGE_CHARS = 2_000
const NEXT_TASK_CHARS = 500
const PAUSE_DELAY_MS = 2_000
const PEOPLE = new Set(['composer', 'bridge'])
const CREDENTIAL_LIKE = /-----BEGIN [\w ]*(?:PRIVATE KEY|SECRET)-----|\b(?:sk[-_][\w-]{8,}|(?:gh[pousr]_|github_pat_|xox[baprs]-|AKIA|ASIA)[\w-]{8,}|eyJ[\w-]+\.[\w-]+\.[\w-]+)|\bBearer\s+\S|(?:api[-_ ]?key|access[-_ ]?token|token|secret|password|credential)["']?\s*[:=]\s*\S|:\/\/[^\s/@:]+:[^\s/@]+@/i

const SWITCHES = 'Does the new message start a different task from the recent work, so that the details of the recent work no longer matter for it?'
const PAUSES = "Did the assistant's last reply finish the work the user asked for, with nothing left running and no question waiting on the user, so this is a good point to pause?"
const PAUSE_SUMMARY = 'The work just reached a good stopping point. Keep what was done and decided, the files touched, and anything the user may follow up on. Drop the working detail.'

type TopicSwitch = { text: string; verdict: string; tokens: number; turnId?: string }

let compacting = false
let compactedSinceAnswer = false
let submitted = 0
let topicSwitch: TopicSwitch | undefined

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

function topicSwitchSummary(text: string): string {
  return 'The conversation switched to a new task. Summarize the earlier work briefly: what was done and decided, '
    + 'the files changed, and anything left open. Preserve the work and decisions for the current task, which began: '
    + clip(text, NEXT_TASK_CHARS)
}

async function jevSure($: EngineInterface, question: string, text: string): Promise<string | undefined> {
  if (CREDENTIAL_LIKE.test(text)) return undefined
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

function canCompact(submission: number): boolean {
  return !compacting && !compactedSinceAnswer && submitted === submission
}

async function compact($: EngineInterface, submission: number, tokens: number, why: string, instructions: string): Promise<void> {
  if (!canCompact(submission)) return
  compacting = true
  try {
    const done = await $.session.compact({ instructions })
    if (done.skip !== undefined || submitted !== submission) return
    compactedSinceAnswer = true
    $.ui.toast(`jev-compact: compacted ${Math.round(tokens / 1000)}k tokens ${why}`)
  } catch (err) {
    $.ui.toast(`jev-compact: could not compact ${why}: ${String(err).slice(0, 160)}`)
  } finally {
    compacting = false
  }
}

async function classifySwitch($: EngineInterface, submission: number, text: string): Promise<TopicSwitch | undefined> {
  if (!canCompact(submission)) return
  const tokens = await contextTokens($)
  if (tokens < SWITCH_FLOOR_TOKENS) return
  const work = recent(await $.session.messages())
  if (!work || !canCompact(submission)) return
  const verdict = await jevSure($, SWITCHES, `Recent work in this session:\n${work}\n\nNew message:\n${clip(text, MESSAGE_CHARS)}`)
  if (verdict) return { text, verdict, tokens }
}

async function compactIfPause($: EngineInterface, submission: number): Promise<void> {
  if (!canCompact(submission)) return
  const tokens = await contextTokens($)
  if (tokens < PAUSE_FLOOR_TOKENS) return
  const work = recent(await $.session.messages())
  if (!work || !canCompact(submission)) return
  const sure = await jevSure($, PAUSES, `Recent work in this session:\n${work}`)
  if (sure) await compact($, submission, tokens, `at a good stopping point (${sure})`, PAUSE_SUMMARY)
}

export const register: Register = on => {
  on('prompt.submit', async ($, e, next) => {
    const submission = ++submitted
    topicSwitch = undefined
    let decision: TopicSwitch | undefined
    if (e.command === undefined && e.isMeta === undefined && e.turnId === undefined && PEOPLE.has(e.origin.kind)) {
      decision = await classifySwitch($, submission, e.text).catch(err => {
        $.ui.log(`jev-compact: ${err}`, { to: 'debug' })
        return undefined
      })
    }
    const done = await next(e)
    if (decision && done.text === e.text && canCompact(submission)) topicSwitch = decision
    return done
  })

  on('turn.start', ($, e, next) => {
    if (e.agentId === undefined && topicSwitch && topicSwitch.turnId === undefined) {
      if (e.text === topicSwitch.text) topicSwitch = { ...topicSwitch, turnId: e.turnId }
      else topicSwitch = undefined
    }
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const submission = submitted
    const done = await next(e)
    if (e.agentId !== undefined || submitted !== submission) return done
    const decision = topicSwitch?.turnId === e.turnId ? topicSwitch : undefined
    if (decision) topicSwitch = undefined
    if (e.reason !== 'answer') return done
    compactedSinceAnswer = false
    if (decision) {
      // Claude refuses compaction while a prompt.submit hook is holding the turn.
      $.clock.after(0, () => compact($, submission, decision.tokens, `after a topic switch (${decision.verdict})`, topicSwitchSummary(decision.text)))
    } else if (!topicSwitch && e.answer.trim()) {
      $.clock.after(PAUSE_DELAY_MS, () => {
        compactIfPause($, submission).catch(err => $.ui.log(`jev-compact: ${err}`, { to: 'debug' }))
      })
    }
    return done
  })

  on('session.compact', async ($, e, next) => {
    const done = await next(e)
    if (e.agentId === undefined && e.trigger !== 'precompute' && done.skip === undefined) {
      compactedSinceAnswer = true
      topicSwitch = undefined
    }
    return done
  })

  on('session.end', ($, e, next) => {
    submitted += 1
    topicSwitch = undefined
    compactedSinceAnswer = false
    return next(e)
  })
}
