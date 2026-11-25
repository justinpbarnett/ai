import { createReadStream } from 'node:fs'
import { createInterface } from 'node:readline'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { approved, classifierArgs, excerpt, recommendation } from '../policy.ts'
import { isApproved, lastUsage, markApproved, type StopEvent, type Usage } from './usage.ts'

type Turn = {
  id: string
  status: string
  items: { type: string; content?: { type: string; text?: string }[] }[]
}

function prompt(turn?: Turn) {
  const messages = turn?.items.filter(item => item.type === 'userMessage')
  if (messages?.length !== 1) return
  const parts = messages[0].content
  if (parts?.length !== 1 || parts[0].type !== 'text') return
  return excerpt(parts[0].text)
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
    await call('initialize', { clientInfo: { name: 'jev-compact', version: '0.3.0' } })
    socket.send(JSON.stringify({ method: 'initialized' }))
    return { call, close: () => socket.close() }
  } catch (error) {
    socket.close()
    throw error
  }
}

type Server = Awaited<ReturnType<typeof connect>>

async function turns(server: Server, threadId: string, limit: number) {
  return (await server.call<{ data: Turn[] }>('thread/turns/list', { threadId, limit, itemsView: 'summary' })).data
}

// Standalone clients can assess their own rollout even without a local daemon.
async function transcriptPrompts(event: StopEvent) {
  if (!event.transcript_path) return
  const input = createReadStream(event.transcript_path)
  const records = createInterface({ input, crlfDelay: Infinity })
  let latest: { id: string; text?: string } | undefined
  let previous: string | undefined
  try {
    for await (const line of records) {
      if (!line.includes('"UserMessage"') || !line.includes('"item_completed"')) continue
      const record = JSON.parse(line)
      const entry = record.payload
      if (record.type !== 'event_msg' || entry?.thread_id !== event.session_id || entry.item?.type !== 'UserMessage') continue
      const parts = entry.item.content
      previous = latest?.text
      latest = { id: entry.turn_id, text: parts?.length === 1 && parts[0].type === 'text' ? excerpt(parts[0].text) : undefined }
    }
  } finally {
    records.close()
    input.destroy()
  }
  if (latest?.id === event.turn_id && latest.text) return { current: latest.text, previous }
}

async function requests(event: StopEvent) {
  try {
    const server = await connect()
    try {
      const [current, prior] = await turns(server, event.session_id, 2)
      if (current?.id === event.turn_id) return { current: prompt(current), previous: prompt(prior) }
      if (current) return
    } finally {
      server.close()
    }
  } catch {
    // The standalone client may own this thread.
  }
  return transcriptPrompts(event)
}

async function assess(event: StopEvent, usage: Usage) {
  const answer = excerpt(event.last_assistant_message)
  if (!answer) return
  const messages = await requests(event)
  if (!messages?.current) return
  const exchange = { current: messages.current, previous: messages.previous, answer }
  const args = classifierArgs(usage.tokens, exchange)
  if (!args) return
  const result = Bun.spawn(args, {
    stdin: new Blob([JSON.stringify(exchange)]), stdout: 'pipe', stderr: 'ignore', timeout: 3500,
  })
  const reply = await new Response(result.stdout).json()
  if (await result.exited !== 0 || !approved(reply)) return
  if ((await lastUsage(event.session_id))?.sample !== usage.sample) return
  await markApproved(event.session_id, usage.sample)
  const message = recommendation(usage.tokens)
  if (message) console.log(JSON.stringify({ systemMessage: message }))
}

async function apply(event: StopEvent) {
  const threadId = event.session_id
  const server = await connect()
  try {
    // The synchronous Stop hook records JEV's decision before Codex finishes the turn.
    const deadline = Date.now() + 8000
    while (Date.now() < deadline) {
      const [latest] = await turns(server, threadId, 1)
      if (latest?.id !== event.turn_id) return
      if (latest.status === 'inProgress') {
        await Bun.sleep(200)
        continue
      }
      const usage = await lastUsage(threadId)
      if (latest.status !== 'completed' || usage?.turn !== event.turn_id || !await isApproved(threadId, usage.sample)) return
      const { thread } = await server.call<{ thread: { status: { type: string }; parentThreadId: string | null } }>(
        'thread/read', { threadId },
      )
      if (thread.status.type !== 'idle' || thread.parentThreadId) return
      const [current] = await turns(server, threadId, 1)
      if (current?.id === event.turn_id && current.status === 'completed') await server.call('thread/compact/start', { threadId })
      return
    }
  } finally {
    server.close()
  }
}

if (import.meta.main) {
  const event = await Bun.stdin.json()
  if (event.hook_event_name === 'Stop' && !event.stop_hook_active && event.last_assistant_message) {
    const usage = await lastUsage(event.session_id)
    if (usage?.turn === event.turn_id && usage.sample) {
      const run = process.argv[2] === 'assess' ? assess(event, usage) : apply(event)
      // Missing evidence, unavailable classifiers and disconnected clients leave the thread alone.
      await run.catch(() => {})
    }
  }
}
