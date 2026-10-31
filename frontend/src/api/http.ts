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

export function playerTokenKey(roomCode: string): string {
  return `chips_player_token_${roomCode.toUpperCase()}`
}

export function getPlayerToken(roomCode: string): string | null {
  return localStorage.getItem(playerTokenKey(roomCode))
}

export function setPlayerToken(roomCode: string, token: string): void {
  localStorage.setItem(playerTokenKey(roomCode), token)
}

class ApiError extends Error {
  code?: string
  constructor(message: string, code?: string) {
    super(message)
    this.code = code
  }
}

async function request(path: string, body?: unknown, auth = true): Promise<any> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (auth) {
    const token = getSessionToken()
    if (token) headers['X-Session-Token'] = token
  }
  const res = await fetch(`/api${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body ?? {}),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new ApiError(data.message || data.detail || 'Request failed', data.code)
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
