import { useState } from 'react'
import type { RoomState } from '../types'

export function Lobby({
  room,
  mySeatId,
  send,
}: {
  room: RoomState
  mySeatId: number
  send: (payload: Record<string, unknown>) => void
}) {
  const isHost = mySeatId === room.host_seat_id
  const [sb, setSb] = useState(room.config.small_blind)
  const [bb, setBb] = useState(room.config.big_blind)
  const [stack, setStack] = useState(room.config.starting_stack)

  function saveConfig(e: React.FormEvent) {
    e.preventDefault()
    send({
      type: 'update_room_config',
      small_blind: sb,
      big_blind: bb,
      starting_stack: stack,
      raise_presets: room.config.raise_presets,
    })
  }

  return (
    <div className="screen">
      <div className="card center-text">
        <h2>Room {room.code}</h2>
        <p className="muted">Share this code with other players at the table.</p>
      </div>

      <div className="card">
        <h3>Players ({room.players.length})</h3>
        <div className="seat-list">
          {room.players.map((p) => (
            <div key={p.seat_id} className={`seat ${!p.connected ? 'disconnected' : ''}`}>
              <span>
                {p.display_name}
                {p.seat_id === room.host_seat_id && <span className="badge">host</span>}
                {p.seat_id === mySeatId && <span className="badge">you</span>}
                {!p.connected && <span className="badge">disconnected</span>}
              </span>
              <span className="muted">{p.stack} chips</span>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <h3>Table Stakes</h3>
        {isHost ? (
          <form onSubmit={saveConfig}>
            <div className="field">
              <label>Small blind</label>
              <input type="number" min={1} value={sb} onChange={(e) => setSb(Number(e.target.value))} />
            </div>
            <div className="field">
              <label>Big blind</label>
              <input type="number" min={1} value={bb} onChange={(e) => setBb(Number(e.target.value))} />
            </div>
            <div className="field">
              <label>Starting stack</label>
              <input type="number" min={1} value={stack} onChange={(e) => setStack(Number(e.target.value))} />
            </div>
            <button className="btn" type="submit">
              Save
            </button>
          </form>
        ) : (
          <p className="muted">
            Blinds {room.config.small_blind}/{room.config.big_blind}, starting stack {room.config.starting_stack}.
            Only the host can change this before the first hand.
          </p>
        )}
      </div>

      <button
        className="btn btn-primary"
        disabled={room.players.length < 2}
        onClick={() => send({ type: 'start_hand' })}
      >
        Start Hand
      </button>
      {room.players.length < 2 && <p className="muted center-text">Need at least 2 players to start.</p>}
    </div>
  )
}
