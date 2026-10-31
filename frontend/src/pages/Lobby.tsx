import { useState } from 'react'
import { RoomCodeCard } from '../components/RoomCodeCard'
import type { RoomState } from '../types'

export function Lobby({
  room,
  mySeatId,
  send,
  onLeave,
}: {
  room: RoomState
  mySeatId: number
  send: (payload: Record<string, unknown>) => void
  onLeave: () => void
}) {
  const isHost = mySeatId === room.host_seat_id
  const [sb, setSb] = useState(room.config.small_blind)
  const [bb, setBb] = useState(room.config.big_blind)
  const [stack, setStack] = useState(room.config.starting_stack)
  const [rotateDealer, setRotateDealer] = useState(room.config.rotate_dealer)

  function saveConfig(e: React.FormEvent) {
    e.preventDefault()
    send({
      type: 'update_room_config',
      small_blind: sb,
      big_blind: bb,
      starting_stack: stack,
      raise_presets: room.config.raise_presets,
      rotate_dealer: rotateDealer,
    })
  }

  return (
    <div className="screen">
      <RoomCodeCard code={room.code} />

      <div className="card">
        <h3>Players ({room.players.length})</h3>
        <div className="seat-list">
          {room.players.map((p) => (
            <div key={p.seat_id} className={`seat ${!p.connected ? 'disconnected' : ''}`}>
              <span>
                <span className={`status-dot ${p.connected ? 'connected' : 'disconnected'}`} />
                {p.display_name}
                {p.seat_id === room.host_seat_id && <span className="badge">HOST</span>}
                {p.seat_id === mySeatId && <span className="badge">YOU</span>}
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
            <div className="field">
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <input type="checkbox" checked={rotateDealer} onChange={(e) => setRotateDealer(e.target.checked)} />
                Rotate dealer duties each hand
              </label>
              <p className="muted" style={{ marginTop: '0.1rem' }}>
                When on, starting a hand and declaring the showdown winner is done by whoever holds the dealer
                button that hand, instead of always the host.
              </p>
            </div>
            <button className="btn" type="submit">
              Save
            </button>
          </form>
        ) : (
          <p className="muted">
            Blinds {room.config.small_blind}/{room.config.big_blind} · Starting stack {room.config.starting_stack} ·
            Dealer duties {room.config.rotate_dealer ? 'rotate each hand' : 'stay with the host'}.
            Only the host can change this before the first hand.
          </p>
        )}
      </div>

      {isHost ? (
        <>
          <button
            className="btn btn-primary"
            disabled={room.players.length < 2}
            onClick={() => send({ type: 'start_hand' })}
          >
            Start Hand
          </button>
          {room.players.length < 2 && <p className="muted center-text">Need at least 2 players to start.</p>}
        </>
      ) : (
        <p className="muted center-text">Waiting for the host to start the hand…</p>
      )}

      <button className="link-btn" onClick={onLeave} style={{ alignSelf: 'center' }}>
        Leave Room
      </button>
    </div>
  )
}
