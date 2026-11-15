import { afterEach, describe, expect, it, vi } from 'vitest'

// The client caches the session token per page load, so each test loads a fresh copy of the module.
async function freshClient() {
  vi.resetModules()
  return import('../lib/api')
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

afterEach(() => vi.unstubAllGlobals())

describe('api client', () => {
  it('sends the session token and turns error bodies into ApiError', async () => {
    const calls: [string, RequestInit | undefined][] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push([url, init])
      if (url === '/api/session') return json(200, { token: 'tok-1' })
      return json(400, { error: 'invalid_input', message: '7203.T is listed on an exchange this app does not support.' })
    }))
    const { api, ApiError } = await freshClient()
    const err = await api.analysis('7203.T').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(400)
    expect(err.code).toBe('invalid_input')
    expect(err.message).toContain('does not support')
    expect(err.retryable).toBe(false)
    const headers = calls.find(([u]) => u.includes('/analysis'))![1]!.headers as Record<string, string>
    expect(headers['X-Analytivest-Token']).toBe('tok-1')
  })

  it('refreshes an expired token once and retries', async () => {
    let n = 0
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/session') return json(200, { token: `tok-${++n}` })
      const tok = (init!.headers as Record<string, string>)['X-Analytivest-Token']
      return tok === 'tok-1' ? json(401, { error: 'unauthorised' }) : json(200, { rows: [], errors: [] })
    }))
    const { api } = await freshClient()
    await expect(api.compare(['AAPL'])).resolves.toEqual({ rows: [], errors: [] })
  })
})
