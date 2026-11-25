import { expect, test } from 'bun:test'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { approved, classifierArgs, excerpt } from '../jev-compact/policy.ts'

const root = join(import.meta.dir, '../jev-compact/codex')

test('a smaller context needs switch evidence and an uncertain verdict defers', () => {
  const exchange = { current: 'Count the apples', answer: 'Three apples.' }
  expect(classifierArgs(89_999, { ...exchange, previous: 'Design a door' })).toBeUndefined()
  expect(classifierArgs(100_000, exchange)).toBeUndefined()
  expect(classifierArgs(95_000, { ...exchange, previous: 'Design a door' })?.join(' ')).toContain('independent tasks')
  expect(classifierArgs(120_000, exchange)).toBeDefined()
  expect(approved({ answer: 'continuing', confidence: 1 })).toBe(false)
  expect(approved({ answer: 'compact', confidence: 0.79 })).toBe(false)
  expect(approved({ answer: 'compact', confidence: 0.8 })).toBe(true)
  expect(approved({ answer: 'compact', confidence: 1.1 })).toBe(false)
  expect(excerpt('x'.repeat(800) + ' Which option should we test?')).toEndWith('Which option should we test?')
})

test('only a JEV-approved, answered high-context turn produces a strong recommendation', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'jev-boundary-'))
  const input = { session_id: 'main', turn_id: 'first', transcript_path: join(dir, 'thread.jsonl') }
  const env = { ...process.env, PLUGIN_DATA: dir, CODEX_HOME: dir, PATH: dir + ':' + process.env.PATH }
  async function hook(script: string, event: object, ...args: string[]) {
    const child = Bun.spawn([process.execPath, join(root, script), ...args], {
      env, stdin: new Blob([JSON.stringify({ ...input, ...event })]), stdout: 'pipe', stderr: 'pipe',
    })
    const output = await new Response(child.stdout).text()
    expect(await child.exited).toBe(0)
    return output
  }
  const usage = (tokens: number) => hook('usage.ts', {
    hook_event_name: 'PostModelRequest', kind: 'sampling', thread_id: 'main', status: 'completed',
    token_usage: { total_tokens: tokens },
  })
  const stop = (message: string, turn = 'first') => hook('compact.ts', {
    hook_event_name: 'Stop', last_assistant_message: message, turn_id: turn,
  }, 'assess')
  try {
    await writeFile(input.transcript_path, JSON.stringify({ type: 'event_msg', payload: {
      type: 'item_completed', thread_id: 'main', turn_id: 'first',
      item: { type: 'UserMessage', content: [{ type: 'text', text: 'Count the apples.' }] },
    } }) + '\n')
    await writeFile(join(dir, 'arete'), '#!/bin/sh\ncat > "$PLUGIN_DATA/exchange"\ncat "$PLUGIN_DATA/verdict"\n', { mode: 0o700 })
    const verdict = (answer: string, confidence: number) => writeFile(join(dir, 'verdict'), JSON.stringify({ answer, confidence }))
    await usage(180_000)
    expect(await hook('usage.ts', { hook_event_name: 'PostToolUse' })).toBe('')
    await verdict('continuing', 1)
    expect(await stop('Which basket?')).toBe('')
    expect(JSON.parse(await Bun.file(join(dir, 'exchange')).text()).answer).toBe('Which basket?')
    await verdict('compact', 0.72)
    expect(await stop('Three apples.')).toBe('')
    await writeFile(join(dir, 'verdict'), 'unavailable')
    expect(await stop('Three apples.')).toBe('')
    await verdict('compact', 0.99)
    expect(await stop('Three apples.', 'stale')).toBe('')
    expect(await stop('password=abc')).toBe('')
    await usage(150_000)
    expect(await stop('Three apples.')).toBe('')
    await usage(150_001)
    expect(JSON.parse(await stop('Three apples.')).systemMessage).toContain('150,001 tokens')
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
})
