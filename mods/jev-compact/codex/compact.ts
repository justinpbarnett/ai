import { homedir } from 'node:os'
import { join } from 'node:path'
import { CREDENTIAL_LIKE, PAUSES, PAUSE_FLOOR_TOKENS, SURE, SWITCHES } from '../policy.ts'
import { lastUsage, type StopEvent } from './usage.ts'

type Turn = {
  id: string
  status: string
  items: { type: string; content?: { type: string; text?: string }[] }[]
}

const LOCAL_ONLY = /^(?:!|\/)|```|~~~|file:\/\/|<(?:file|skill|attachment)\b|(?:^|\s)@\S/i
const PRIVATE_PATH = /(?:^|[\s/\\'"=@])(?:\.env(?:\.[\w.-]+)?|\.ssh|\.aws|\.gnupg|auth\.json|credentials(?:\.json)?|id_(?:rsa|ed25519))(?:$|[\s/\\'";])/i

function excerpt(text?: string) {
  const value = text?.trim()
  if (value && !CREDENTIAL_LIKE.test(value) && !PRIVATE_PATH.test(value) && !LOCAL_ONLY.test(value)) {
    return value.slice(0, 512)
  }
}

function prompt(turn?: Turn) {
  const messages = turn?.items.filter(item => item.type === 'userMessage')
  if (messages?.length !== 1) return
  const parts = messages[0].content
  if (parts?.length !== 1 || parts[0].type !== 'text') return
  return excerpt(parts[0].text)
}

async function sure(question: string, excerpts: Record<string, string>) {
  try {
    const result = Bun.spawn(['arete', 'ask', question, '--json'], {
      stdin: new Blob([JSON.stringify(excerpts)]), stdout: 'pipe', stderr: 'ignore', timeout: 3500,
    })
    const reply = await new Response(result.stdout).json()
    return await result.exited === 0 && reply?.answer === 'yes' && reply.confidence >= SURE
  } catch {
    return false
  }
}

// Connect only to the existing local daemon. Never resume a thread in another server.
async function connect() {
  const home = process.env.CODEX_HOME || join(homedir(), '.codex')
  const socket = new WebSocket('ws+unix://' + join(home, 'app-server-control/app-server-control.sock'))
  let id = 0
  try {
    await new Promise<void>((resolve, reject) => {
      socket.onopen = () => resolve()
      socket.onerror = () => reject(new Error('Codex daemon unavailable'))
    })
    async function call<T = unknown>(method: string, params: object) {
      const request = ++id
      return new Promise<T>((resolve, reject) => {
        socket.onclose = () => reject(new Error('Codex daemon disconnected'))
        socket.onmessage = event => {
          const reply = JSON.parse(event.data)
          if (reply.id !== request) return
          if (reply.error) reject(new Error(reply.error.message))
          else resolve(reply.result)
        }
        socket.send(JSON.stringify({ id: request, method, params }))
      })
    }
    await call('initialize', { clientInfo: { name: 'jev-compact', version: '0.2.0' } })
    socket.send(JSON.stringify({ method: 'initialized' }))
    return { call, close: () => socket.close() }
  } catch (error) {
    socket.close()
    throw error
  }
}

async function compact(event: StopEvent) {
  const usage = await lastUsage(event.session_id)
  if (!usage || usage.turn !== event.turn_id || event.stop_hook_active || !event.last_assistant_message) return
  const threadId = event.session_id
  const server = await connect()
  try {
    const turns = async () => (await server.call<{ data: Turn[] }>(
      'thread/turns/list', { threadId, limit: 2, itemsView: 'summary' },
    )).data
    const [current, previous] = await turns()
    if (current?.id !== event.turn_id) return
    const request = prompt(current)
    if (!request) return
    const prior = prompt(previous)
    const answer = excerpt(event.last_assistant_message)
    const switched = prior && prior !== request && await sure(SWITCHES, { previous: prior, current: request })
    if (!switched && !(usage.tokens >= PAUSE_FLOOR_TOKENS && answer && await sure(PAUSES, { request, answer }))) return

    // The background Stop hook may finish after a new prompt or a manual /compact.
    const { thread } = await server.call<{ thread: { status: { type: string }; parentThreadId: string | null } }>(
      'thread/read', { threadId },
    )
    const [latest] = await turns()
    if (thread.status.type !== 'idle' || thread.parentThreadId || latest?.id !== event.turn_id || latest.status !== 'completed') return
    await server.call('thread/compact/start', { threadId })
  } finally {
    server.close()
  }
}

if (import.meta.main) {
  const event = await Bun.stdin.json()
  // Standalone clients may have no daemon owning this thread. The local usage warning still runs.
  if (event.hook_event_name === 'Stop') await compact(event).catch(() => {})
}
