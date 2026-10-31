// Same-origin by default (the LAN quick-start mode where this backend also
// serves the built frontend). Set at build time when the frontend is
// published separately (e.g. GitHub Pages) from a backend on its own
// domain -- see DEPLOYMENT.md.
export const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')

const SESSION_TOKEN_KEY = 'chips_session_token'
const LAST_ROOM_KEY = 'chips_last_room_code'

export function getLastRoomCode(): string | null {
  return localStorage.getItem(LAST_ROOM_KEY)
}

export function setLastRoomCode(code: string): void {
  localStorage.setItem(LAST_ROOM_KEY, code)
}

export function clearLastRoomCode(): void {
  localStorage.removeItem(LAST_ROOM_KEY)
}

export function getSessionToken(): string | null {
  return localStorage.getItem(SESSION_TOKEN_KEY)
}

export function setSessionToken(token: string): void {
  localStorage.setItem(SESSION_TOKEN_KEY, token)
}

export function clearSessionToken(): void {
  localStorage.removeItem(SESSION_TOKEN_KEY)
}

export function playerTokenKey(roomCode: string): string {
  return `chips_player_token_${roomCode.toUpperCase()}`
}

export function getPlayerToken(roomCode: string): string | null {
  return localStorage.getItem(playerTokenKey(roomCode))
}

export function setPlayerToken(roomCode: string, token: string): void {
  localStorage.setItem(playerTokenKey(roomCode), token)
}

export function clearPlayerToken(roomCode: string): void {
  localStorage.removeItem(playerTokenKey(roomCode))
}

class ApiError extends Error {
  code?: string
  status?: number
  constructor(message: string, code?: string, status?: number) {
    super(message)
    this.code = code
    this.status = status
  }
}

async function request(path: string, body?: unknown, auth = true): Promise<any> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (auth) {
    const token = getSessionToken()
    if (token) headers['X-Session-Token'] = token
  }
  const res = await fetch(`${API_BASE}/api${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body ?? {}),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    // Session tokens live only in the backend's process memory (see
    // README's "in-memory only" limitation) -- any backend restart
    // silently invalidates every outstanding token. Without this, a
    // stale token in localStorage would permanently skip the passphrase
    // gate while every real request kept failing with no way to recover
    // short of manually clearing storage.
    if (res.status === 401) clearSessionToken()
    throw new ApiError(data.message || data.detail || 'Request failed', data.code, res.status)
  }
  return data
}

export async function submitPassphrase(passphrase: string): Promise<void> {
  const data = await request('/auth/passphrase', { passphrase }, false)
  setSessionToken(data.session_token)
}

export async function createRoom(params: {
  display_name: string
  small_blind: number
  big_blind: number
  starting_stack: number
  raise_presets: number[]
}): Promise<{ room_code: string; seat_id: number; player_token: string }> {
  const data = await request('/rooms', params)
  setPlayerToken(data.room_code, data.player_token)
  setLastRoomCode(data.room_code)
  return data
}

export async function joinRoom(
  code: string,
  display_name: string,
): Promise<{ room_code: string; seat_id: number; player_token: string }> {
  const data = await request(`/rooms/${code}/join`, { display_name })
  setPlayerToken(data.room_code, data.player_token)
  setLastRoomCode(data.room_code)
  return data
}

export async function rejoinRoom(code: string): Promise<{ room_code: string; seat_id: number } | null> {
  const token = getPlayerToken(code)
  if (!token) return null
  try {
    return await request(`/rooms/${code}/rejoin`, { player_token: token })
  } catch {
    return null
  }
}

export { ApiError }
