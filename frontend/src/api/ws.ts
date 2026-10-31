import { API_BASE, getPlayerToken, getSessionToken } from './http'
import type { RoomState } from '../types'

export type WsEvent =
  | { type: 'state_sync'; room: RoomState }
  | { type: 'error'; code: string; message: string }
  | { type: 'pong' }

export class RoomSocket {
  private ws: WebSocket | null = null
  private heartbeat: number | null = null
  private closedByUser = false
  private reconnectDelay = 1000
  private roomCode: string
  private onEvent: (e: WsEvent) => void
  private onConnectionChange: (connected: boolean) => void

  constructor(roomCode: string, onEvent: (e: WsEvent) => void, onConnectionChange: (connected: boolean) => void) {
    this.roomCode = roomCode
    this.onEvent = onEvent
    this.onConnectionChange = onConnectionChange
  }

  connect(): void {
    this.closedByUser = false
    const sessionToken = getSessionToken()
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
    const url = `${wsOrigin}/ws/${this.roomCode}?session_token=${encodeURIComponent(
      sessionToken ?? '',
    )}&player_token=${encodeURIComponent(playerToken ?? '')}`
    const ws = new WebSocket(url)
    this.ws = ws

    ws.onopen = () => {
      this.reconnectDelay = 1000
      this.onConnectionChange(true)
      this.heartbeat = window.setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }))
      }, 25000)
    }

    ws.onmessage = (ev) => {
      const data = JSON.parse(ev.data) as WsEvent
      this.onEvent(data)
    }

    ws.onclose = () => {
      this.onConnectionChange(false)
      if (this.heartbeat) window.clearInterval(this.heartbeat)
      if (!this.closedByUser) {
        window.setTimeout(() => this.connect(), this.reconnectDelay)
        this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, 10000)
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
