import { useEffect, useState } from 'react'
import { clearLastRoomCode, clearPlayerToken, getLastRoomCode, rejoinRoom } from './api/http'
import { Home } from './pages/Home'
import { Lobby } from './pages/Lobby'
import { Table } from './pages/Table'
import { useRoomConnection } from './state/store'

type Stage = 'checking' | 'home' | 'room'

function App() {
  const [stage, setStage] = useState<Stage>('checking')
  const [roomCode, setRoomCode] = useState<string | null>(null)
  const [mySeatId, setMySeatId] = useState<number | null>(null)
  // A QR code / shared link can carry ?join=CODE. Parsed once; the query
  // string is then cleared so a later refresh doesn't keep re-applying it.
  const [deepLinkJoinCode] = useState<string | null>(() => {
    const code = new URLSearchParams(window.location.search).get('join')
    if (code) window.history.replaceState(null, '', window.location.pathname)
    return code
  })

  useEffect(() => {
    async function boot() {
      const lastCode = getLastRoomCode()
      if (lastCode) {
        const rejoined = await rejoinRoom(lastCode)
        if (rejoined) {
          setRoomCode(rejoined.room_code)
          setMySeatId(rejoined.seat_id)
          setStage('room')
          return
        }
      }
      setStage('home')
    }
    boot()
  }, [])

  if (stage === 'checking') return null

  if (stage === 'home' || !roomCode || mySeatId === null) {
    return (
      <Home
        onEnterRoom={(code) => {
          // seat_id is recovered via the room's own websocket-less rejoin
          // right after create/join already stored the player_token
          rejoinRoom(code).then((r) => {
            if (r) {
              setRoomCode(r.room_code)
              setMySeatId(r.seat_id)
              setStage('room')
            }
          })
        }}
        initialJoinCode={deepLinkJoinCode}
      />
    )
  }

  return (
    <RoomView
      roomCode={roomCode}
      mySeatId={mySeatId}
      onLeave={() => {
        setRoomCode(null)
        setMySeatId(null)
        setStage('home')
      }}
    />
  )
}

function RoomView({
  roomCode,
  mySeatId,
  onLeave,
}: {
  roomCode: string
  mySeatId: number
  onLeave: () => void
}) {
  const { room, connected, error, send } = useRoomConnection(roomCode)

  function leaveRoom() {
    if (!window.confirm('Leave this room? You can rejoin with the room code as long as it still exists.')) return
    clearPlayerToken(roomCode)
    clearLastRoomCode()
    onLeave()
  }

  if (!room) {
    return (
      <div className="screen">
        <div className="card center-text">
          <p>Connecting to room {roomCode}…</p>
        </div>
      </div>
    )
  }

  return (
    <>
      {!connected && (
        <div className="error-banner" style={{ margin: '0.5rem' }}>
          Reconnecting…
        </div>
      )}
      {error && (
        <div className="error-banner" style={{ margin: '0.5rem' }}>
          {error}
        </div>
      )}
      {room.phase === 'lobby' ? (
        <Lobby room={room} mySeatId={mySeatId} send={send} onLeave={leaveRoom} />
      ) : (
        <Table room={room} mySeatId={mySeatId} send={send} onLeave={leaveRoom} />
      )}
    </>
  )
}

export default App
