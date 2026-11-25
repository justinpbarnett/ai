import { expect, test } from 'bun:test'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { recommendation } from '../jev-compact/policy.ts'

const script = join(import.meta.dir, '../jev-compact/codex/usage.ts')

test('the strong warning starts one token above 150,000', () => {
  expect(recommendation(150_000)).toBeUndefined()
  expect(recommendation(150_001)).toContain('150,001 tokens. Strongly recommend running /compact')
})

test('Codex warns once across parallel tools, ignores stale reports, and rearms after relief', async () => {
  const data = await mkdtemp(join(tmpdir(), 'jev-compact-test-'))
  const common = { session_id: 'main', turn_id: 'first' }
  async function hook(event: object) {
    const child = Bun.spawn([process.execPath, script], {
      env: { ...process.env, PLUGIN_DATA: data },
      stdin: new Blob([JSON.stringify({ ...common, ...event })]), stdout: 'pipe', stderr: 'pipe',
    })
    const output = await new Response(child.stdout).text()
    expect(await child.exited).toBe(0)
    return output
  }
  const usage = (tokens: number) => hook({
    hook_event_name: 'PostModelRequest', kind: 'sampling', thread_id: 'main', status: 'completed',
    token_usage: { total_tokens: tokens, cached_input_tokens: 100_000 },
  })
  const tool = { hook_event_name: 'PostToolUse' }
  const stop = { hook_event_name: 'Stop' }
  try {
    await usage(150_000)
    expect(await hook(stop)).toBe('')
    await usage(150_001)
    expect(await hook({ ...tool, turn_id: 'other' })).toBe('')
    expect(await hook({ ...tool, session_id: 'other' })).toBe('')
    const warnings = (await Promise.all([hook(tool), hook(tool), hook(stop)])).filter(Boolean)
    expect(warnings).toHaveLength(1)
    expect(JSON.parse(warnings[0]).systemMessage).toBe(recommendation(150_001))
    await usage(175_000)
    expect(await hook(stop)).toBe('')
    await usage(50_000)
    await usage(150_002)
    expect(JSON.parse(await hook(stop)).systemMessage).toBe(recommendation(150_002))
  } finally {
    await rm(data, { recursive: true, force: true })
  }
})
