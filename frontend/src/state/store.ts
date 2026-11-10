import { useEffect, useRef, useState } from 'react'
import { RoomSocket } from '../api/ws'
import type { RoomState } from '../types'

export interface RoomConnection {
  room: RoomState | null
  connected: boolean
  error: string | null
  send: (payload: Record<string, unknown>) => void
}

export function useRoomConnection(roomCode: string | null): RoomConnection {
  const [room, setRoom] = useState<RoomState | null>(null)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const socketRef = useRef<RoomSocket | null>(null)

  useEffect(() => {
    if (!roomCode) return
    const socket = new RoomSocket(
      roomCode,
      (event) => {
        if (event.type === 'state_sync') {
          setRoom(event.room)
          setError(null)
        } else if (event.type === 'error') {
          setError(event.message)
          // A rate-limited message is *dropped*, so no state_sync follows to
          // clear the banner the way every other error path relies on.
          // Expire it on a timer instead.
          if (event.code === 'RATE_LIMITED' || event.code === 'MESSAGE_TOO_LARGE') {
            window.setTimeout(() => setError(null), 4000)
          }
        }
      },
      setConnected,
      setError,
    )
    socketRef.current = socket
    socket.connect()
    return () => socket.close()
  }, [roomCode])

  const send = (payload: Record<string, unknown>) => socketRef.current?.send(payload)

  return { room, connected, error, send }
}
