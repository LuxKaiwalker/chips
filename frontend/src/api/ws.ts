import { API_BASE, clearLastRoomCode, getPlayerToken } from './http'

// Matches ws_router.py's close codes: 4404 = room or player not found
// (e.g. a stale room after a backend restart, which wipes all in-memory
// rooms), not worth retrying with the same player token -- see the onclose
// handler below. 4429 = rate limited, which *is* worth retrying, just much
// later; the close `reason` carries the server's retry hint in seconds (a
// WebSocket close has no headers, so that's the only channel for it).
const CLOSE_ROOM_NOT_FOUND = 4404
const CLOSE_RATE_LIMITED = 4429

const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 30000
const RATE_LIMITED_MIN_MS = 5000
const RATE_LIMITED_FALLBACK_MS = 15000
import type { RoomState } from '../types'

export type WsEvent =
  | { type: 'state_sync'; room: RoomState }
  | { type: 'error'; code: string; message: string }
  | { type: 'pong' }

export class RoomSocket {
  private ws: WebSocket | null = null
  private heartbeat: number | null = null
  private closedByUser = false
  private reconnectDelay = RECONNECT_BASE_MS
  private roomCode: string
  private onEvent: (e: WsEvent) => void
  private onConnectionChange: (connected: boolean) => void
  private onNotice: (msg: string | null) => void

  constructor(
    roomCode: string,
    onEvent: (e: WsEvent) => void,
    onConnectionChange: (connected: boolean) => void,
    onNotice: (msg: string | null) => void = () => {},
  ) {
    this.roomCode = roomCode
    this.onEvent = onEvent
    this.onConnectionChange = onConnectionChange
    this.onNotice = onNotice
  }

  connect(): void {
    this.closedByUser = false
    const playerToken = getPlayerToken(this.roomCode)
    // Same-origin by default; when API_BASE points at a separately-hosted
    // backend (see DEPLOYMENT.md), derive the ws(s) origin from it instead.
    let wsOrigin: string
    if (API_BASE) {
      const base = new URL(API_BASE)
      wsOrigin = `${base.protocol === 'https:' ? 'wss' : 'ws'}://${base.host}`
    } else {
      wsOrigin = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`
    }
    const url = `${wsOrigin}/ws/${this.roomCode}?player_token=${encodeURIComponent(playerToken ?? '')}`
    const ws = new WebSocket(url)
    this.ws = ws

    ws.onopen = () => {
      this.reconnectDelay = RECONNECT_BASE_MS
      this.onNotice(null)
      this.onConnectionChange(true)
      this.heartbeat = window.setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }))
      }, 25000)
    }

    ws.onmessage = (ev) => {
      // Guarded: an unparseable frame must not throw out of the handler and
      // take the client down. (A NaN in a serialized stack used to do
      // exactly that -- JSON.parse rejects the bare `NaN` that Python's
      // json.dumps emits -- breaking every client in the room at once.)
      let data: WsEvent
      try {
        data = JSON.parse(ev.data) as WsEvent
      } catch {
        this.onNotice('Received a malformed update from the server.')
        return
      }
      this.onEvent(data)
    }

    ws.onclose = (ev) => {
      this.onConnectionChange(false)
      if (this.heartbeat) window.clearInterval(this.heartbeat)

      if (ev.code === CLOSE_ROOM_NOT_FOUND) {
        // The room itself (or this player's seat) is gone -- the backend
        // restarted and its in-memory rooms went with it. Drop back to Home
        // instead of retrying a room that no longer exists.
        clearLastRoomCode()
        window.location.reload()
        return
      }
      if (ev.code === CLOSE_RATE_LIMITED) {
        // Deliberately does NOT reload and does NOT clear any token: the
        // credentials are fine, there have just been too many attempts.
        // Reloading would re-handshake immediately and dig the hole deeper.
        // Back off hard, then fall through to the normal retry path so it
        // heals on its own once the window clears.
        const hinted = Number.parseInt(ev.reason, 10)
        this.reconnectDelay = Math.max(
          RATE_LIMITED_MIN_MS,
          Number.isFinite(hinted) && hinted > 0 ? hinted * 1000 : RATE_LIMITED_FALLBACK_MS,
        )
        this.onNotice('Too many connection attempts — retrying shortly.')
      }
      if (!this.closedByUser) {
        // Jittered, because without it a backend restart synchronises every
        // phone at the table into the same retry instant and they stay
        // wedged in the connect limiter together.
        const jittered = this.reconnectDelay * (0.5 + Math.random())
        window.setTimeout(() => this.connect(), jittered)
        this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, RECONNECT_MAX_MS)
      }
    }
  }

  send(payload: Record<string, unknown>): void {
    this.ws?.send(JSON.stringify(payload))
  }

  close(): void {
    this.closedByUser = true
    if (this.heartbeat) window.clearInterval(this.heartbeat)
    this.ws?.close()
  }
}
