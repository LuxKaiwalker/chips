import { useEffect, useState } from 'react'
import { getLastRoomCode, getSessionToken, rejoinRoom } from './api/http'
import { PassphraseGate } from './pages/PassphraseGate'
import { Home } from './pages/Home'
import { Lobby } from './pages/Lobby'
import { Table } from './pages/Table'
import { useRoomConnection } from './state/store'

type Stage = 'checking' | 'gate' | 'home' | 'room'

function App() {
  const [stage, setStage] = useState<Stage>('checking')
  const [roomCode, setRoomCode] = useState<string | null>(null)
  const [mySeatId, setMySeatId] = useState<number | null>(null)

  useEffect(() => {
    async function boot() {
      if (!getSessionToken()) {
        setStage('gate')
        return
      }
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

  if (stage === 'gate') {
    return <PassphraseGate onSuccess={() => setStage('home')} />
  }

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
      />
    )
  }

  return <RoomView roomCode={roomCode} mySeatId={mySeatId} />
}

function RoomView({ roomCode, mySeatId }: { roomCode: string; mySeatId: number }) {
  const { room, connected, error, send } = useRoomConnection(roomCode)

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
        <Lobby room={room} mySeatId={mySeatId} send={send} />
      ) : (
        <Table room={room} mySeatId={mySeatId} send={send} />
      )}
    </>
  )
}

export default App
