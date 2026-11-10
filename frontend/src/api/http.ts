// Same-origin by default (the LAN quick-start mode where this backend also
// serves the built frontend). Set at build time when the frontend is
// published separately (e.g. GitHub Pages) from a backend on its own
// domain -- see DEPLOYMENT.md.
export const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')

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
  retryAfter?: number
  constructor(message: string, code?: string, status?: number, retryAfter?: number) {
    super(message)
    this.code = code
    this.status = status
    this.retryAfter = retryAfter
  }
}

function throttleMessage(status: number, retryAfter?: number): string {
  const wait = retryAfter && retryAfter > 0 ? ` Try again in ${retryAfter}s.` : ' Try again shortly.'
  return status === 503 ? `The server is at capacity.${wait}` : `Too many requests.${wait}`
}

async function request(path: string, body?: unknown): Promise<any> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const res = await fetch(`${API_BASE}/api${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body ?? {}),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    // Throttle responses need handling before the generic path below.
    // nginx's own limit_req rejection is an HTML error page with no JSON
    // body at all, so `data` is empty and the generic branch would render a
    // bare "Request failed" with no hint that waiting would fix it.
    if (res.status === 429 || res.status === 503) {
      const header = Number.parseInt(res.headers.get('Retry-After') ?? '', 10)
      const retryAfter = Number.isFinite(header) && header > 0 ? header : undefined
      throw new ApiError(
        data.message || data.detail || throttleMessage(res.status, retryAfter),
        data.code,
        res.status,
        retryAfter,
      )
    }
    throw new ApiError(data.message || data.detail || 'Request failed', data.code, res.status)
  }
  return data
}

export async function createRoom(params: {
  display_name: string
  small_blind: number
  big_blind: number
  starting_stack: number
  raise_presets: number[]
  rotate_dealer: boolean
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
