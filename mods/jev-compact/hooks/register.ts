import type { EngineInterface, Register } from 'claude-code'
import { approved, classifierArgs, excerpt, recommendation, SWITCH_FLOOR_TOKENS } from '../policy.ts'

const SUMMARY = 'Summarize the work and decisions at this stopping point. Preserve the current objective, files changed, verification results, and anything the user may return to.'
let generation = 0
let compacting = false

async function consider($: EngineInterface, turn: number, reply: string) {
  if (generation !== turn || compacting) return
  const tokens = (await $.session.usage()).context.tokens
  if (typeof tokens !== 'number' || tokens < SWITCH_FLOOR_TOKENS) return
  const requests = (await $.session.messages()).filter(message => message.role === 'user')
  const current = excerpt(requests.at(-1)?.text)
  const answer = excerpt(reply)
  if (!current || !answer || generation !== turn) return
  const exchange = { previous: excerpt(requests.at(-2)?.text), current, answer }
  const args = classifierArgs(tokens, exchange)
  if (!args) return
  const ran = await $.process.run(args, { stdin: JSON.stringify(exchange), timeoutMs: 3500 })
  if (ran.exitCode !== 0 || generation !== turn || compacting || !approved(JSON.parse(ran.stdout))) return

  const advice = recommendation(tokens)
  if (advice) $.ui.toast(advice)
  compacting = true
  try {
    const done = await $.session.compact({ instructions: SUMMARY })
    if (done.skip === undefined) $.ui.toast('JEV found a natural stopping point. Claude compacted the conversation.')
  } finally {
    compacting = false
  }
}

export const register: Register = on => {
  on('prompt.submit', (_, e, next) => {
    generation++
    return next(e)
  })
  on('turn.complete', async ($, e, next) => {
    const turn = generation
    const done = await next(e)
    if (e.agentId === undefined && e.reason === 'answer' && e.answer.trim() && generation === turn) {
      $.clock.after(2000, () => consider($, turn, e.answer).catch(err => $.ui.log(`jev-compact: ${err}`, { to: 'debug' })))
    }
    return done
  })
  on('session.compact', async (_, e, next) => {
    const done = await next(e)
    if (e.agentId === undefined && e.trigger !== 'precompute' && done.skip === undefined) generation++
    return done
  })
  on('session.end', (_, e, next) => {
    generation++
    return next(e)
  })
}
