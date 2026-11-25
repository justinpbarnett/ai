import { createHash, randomUUID } from 'node:crypto'
import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { SWITCH_FLOOR_TOKENS } from '../policy.ts'

export type StopEvent = {
  session_id: string
  turn_id: string
  last_assistant_message?: string
  stop_hook_active?: boolean
  transcript_path?: string | null
}

export type Usage = { turn: string; tokens: number; sample: string }

function usagePath(thread: string) {
  const name = createHash('sha256').update(thread).digest('hex')
  return join(process.env.PLUGIN_DATA!, 'usage', name)
}

export async function lastUsage(thread: string): Promise<Usage | undefined> {
  try {
    return JSON.parse(await readFile(usagePath(thread), 'utf8'))
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
  }
}

export async function markApproved(thread: string, sample: string) {
  await atomicWrite(usagePath(thread) + '.approved', sample)
}

export async function isApproved(thread: string, sample: string) {
  return (await Bun.file(usagePath(thread) + '.approved').text().catch(() => '')) === sample
}

async function atomicWrite(path: string, value: string) {
  const temporary = path + '.' + randomUUID()
  await writeFile(temporary, value, { mode: 0o600 })
  await rename(temporary, path)
}

async function save(thread: string, usage: Usage) {
  await mkdir(join(process.env.PLUGIN_DATA!, 'usage'), { recursive: true, mode: 0o700 })
  await atomicWrite(usagePath(thread), JSON.stringify(usage))
}

if (import.meta.main) {
  const event = await Bun.stdin.json()
  const thread = event.session_id
  if (thread && event.turn_id && !event.agent_id) {
    if (event.hook_event_name === 'PostModelRequest' && event.kind === 'sampling' &&
        event.status === 'completed' && event.thread_id === thread) {
      // total_tokens is per request here. Cached input and reasoning are already included.
      const tokens = event.token_usage?.total_tokens
      if (Number.isSafeInteger(tokens) && tokens >= 0) {
        if (tokens < SWITCH_FLOOR_TOKENS) await rm(usagePath(thread), { force: true })
        else await save(thread, { turn: event.turn_id, tokens, sample: event.request_id ?? randomUUID() })
      }
    }
  }
}
