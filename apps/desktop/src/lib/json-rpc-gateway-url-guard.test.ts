// connect() must reject before WebSocket coerces garbage into
// `ws://<origin>/[object%20Object]` (#68250 stale-emit boot loop).

import { JsonRpcGatewayClient, JsonRpcGatewayError } from '@hermes/shared'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

class FakeSocket {
  static OPEN = 1
  readyState = 0
  addEventListener = vi.fn((type: string, handler: () => void) => {
    if (type === 'open') {
      setTimeout(() => {
        this.readyState = FakeSocket.OPEN
        handler()
      }, 0)
    }
  })
  removeEventListener = vi.fn()
  close = vi.fn()
  send = vi.fn()
}

describe('JsonRpcGatewayClient connect() URL guard', () => {
  beforeEach(() => {
    vi.stubGlobal('WebSocket', FakeSocket) // jsdom has none; class reads WebSocket.OPEN
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('rejects a non-string IPC result object', async () => {
    const client = new JsonRpcGatewayClient()
    await expect(client.connect({ ok: true, wsUrl: 'ws://127.0.0.1:1/api/ws' } as unknown as string)).rejects.toThrow(
      /requires a ws:\/\/ or wss:\/\/ URL string, got type "object"/
    )
  })

  it('rejects a non-ws URL string', async () => {
    const client = new JsonRpcGatewayClient()
    await expect(client.connect('http://127.0.0.1:1234/api/ws')).rejects.toThrow(
      /requires a ws:\/\/ or wss:\/\/ URL string/
    )
  })

  it('rejects a malformed ws URL before opening a socket', async () => {
    const client = new JsonRpcGatewayClient()
    await expect(client.connect('ws://')).rejects.toThrow(/requires a ws:\/\/ or wss:\/\/ URL string/)
    expect(client.connectionState).toBe('idle')
  })

  it('keeps connection state idle on rejection', async () => {
    const client = new JsonRpcGatewayClient()
    await client.connect(undefined as unknown as string).catch(() => undefined)
    expect(client.connectionState).toBe('idle')
  })

  it('accepts ws:// and wss://', async () => {
    for (const url of ['ws://127.0.0.1:1234/api/ws?token=t', 'wss://gw.example.com/api/ws?ticket=t']) {
      const client = new JsonRpcGatewayClient({ socketFactory: () => new FakeSocket() as unknown as WebSocket })
      await client.connect(url)
      expect(client.connectionState).toBe('open')
    }
  })
})

describe('JsonRpcGatewayClient connect() join (#39956 sleep/wake stall)', () => {
  beforeEach(() => {
    vi.stubGlobal('WebSocket', { OPEN: 1, CONNECTING: 0, CLOSED: 3 })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('does not treat a second connect() as success while the first handshake is still in flight', async () => {
    const sockets: Array<{ open: () => void }> = []

    class HungSocket {
      static OPEN = 1
      readyState = 0
      private openHandler: (() => void) | null = null

      addEventListener = (type: string, handler: () => void) => {
        if (type === 'open') {
          this.openHandler = handler
        }
      }

      removeEventListener = vi.fn()
      close = vi.fn()
      send = vi.fn()

      open() {
        this.readyState = HungSocket.OPEN
        this.openHandler?.()
      }
    }

    const client = new JsonRpcGatewayClient({
      connectTimeoutMs: 0,
      socketFactory: () => {
        const socket = new HungSocket()
        sockets.push(socket)

        return socket as unknown as WebSocket
      }
    })

    const first = client.connect('ws://gateway.test/a')
    const second = client.connect('ws://gateway.test/b')

    expect(sockets).toHaveLength(1)
    expect(client.connectionState).toBe('connecting')

    let firstSettled = false
    let secondSettled = false
    void first.then(() => {
      firstSettled = true
    })
    void second.then(() => {
      secondSettled = true
    })
    await Promise.resolve()
    expect(firstSettled).toBe(false)
    expect(secondSettled).toBe(false)

    sockets[0]?.open()
    await Promise.all([first, second])
    expect(client.connectionState).toBe('open')
  })

  it('lets close() fail a hung handshake so the next connect() can dial again', async () => {
    class HungSocket {
      static OPEN = 1
      readyState = 0
      addEventListener = vi.fn()
      removeEventListener = vi.fn()
      close = vi.fn()
      send = vi.fn()
    }

    let sockets = 0

    const client = new JsonRpcGatewayClient({
      connectTimeoutMs: 0,
      socketFactory: () => {
        sockets += 1

        return new HungSocket() as unknown as WebSocket
      }
    })

    const hung = client.connect('ws://gateway.test/a')
    expect(client.connectionState).toBe('connecting')
    client.close()
    await expect(hung).rejects.toThrow('WebSocket connection failed')
    expect(client.connectionState).toBe('closed')

    const retry = client.connect('ws://gateway.test/b')
    expect(sockets).toBe(2)
    // Leave the retry hanging; the point is a new dial started.
    expect(client.connectionState).toBe('connecting')
    client.close()
    await expect(retry).rejects.toThrow('WebSocket connection failed')
  })
})

describe('JsonRpcGatewayClient structured errors', () => {
  it('rejects with JsonRpcGatewayError including code and data', async () => {
    class RespondingSocket {
      static OPEN = 1
      readyState = 0
      private messageHandler: ((event: { data: string }) => void) | null = null

      addEventListener = vi.fn((type: string, handler: (event?: { data: string }) => void) => {
        if (type === 'open') {
          setTimeout(() => {
            this.readyState = RespondingSocket.OPEN
            handler()
          }, 0)
        }

        if (type === 'message') {
          this.messageHandler = handler as (event: { data: string }) => void
        }
      })
      removeEventListener = vi.fn()
      close = vi.fn()
      send = vi.fn((raw: string) => {
        const req = JSON.parse(raw) as { id: string }
        queueMicrotask(() => {
          this.messageHandler?.({
            data: JSON.stringify({
              jsonrpc: '2.0',
              id: req.id,
              error: {
                code: 4018,
                message: 'target user message is no longer in session history',
                data: { user_turn_count: 2, ordinal: 5, segment_ordinal: 3 }
              }
            })
          })
        })
      })
    }

    vi.stubGlobal('WebSocket', RespondingSocket)

    try {
      const client = new JsonRpcGatewayClient({
        requestTimeoutMs: 5_000,
        socketFactory: () => new RespondingSocket() as unknown as WebSocket
      })

      await client.connect('ws://127.0.0.1:1234/api/ws?token=t')

      await expect(client.request('prompt.submit', { session_id: 's' })).rejects.toEqual(
        expect.objectContaining({
          name: 'JsonRpcGatewayError',
          code: 4018,
          message: 'target user message is no longer in session history',
          data: { user_turn_count: 2, ordinal: 5, segment_ordinal: 3 }
        })
      )
      expect(new JsonRpcGatewayError('x')).toBeInstanceOf(Error)
    } finally {
      vi.unstubAllGlobals()
    }
  })
})
