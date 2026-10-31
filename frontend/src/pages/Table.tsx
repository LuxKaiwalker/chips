import type { RoomState } from '../types'
import { ActionPanel } from '../components/ActionPanel'
import { DealingStageBanner } from '../components/DealingStageBanner'
import { DeclareWinnerPanel } from '../components/DeclareWinnerPanel'
import { PotDisplay } from '../components/PotDisplay'
import { RebuyModal } from '../components/RebuyModal'
import { SeatView } from '../components/SeatView'

export function Table({
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
  const hand = room.hand
  const me = room.players.find((p) => p.seat_id === mySeatId)
  const isHost = mySeatId === room.host_seat_id

  return (
    <div className="screen">
      <div className="card center-text">
        <span className="muted">
          Room {room.code} · Blinds {room.config.small_blind}/{room.config.big_blind}
        </span>
        {hand && <h3>Hand #{hand.hand_number}</h3>}
      </div>

      {hand && <DealingStageBanner hand={hand} myStatus={me?.status ?? ''} onAdvance={() => send({ type: 'advance_runout' })} />}
      {hand && <PotDisplay hand={hand} />}

      <div className="card">
        <div className="seat-list">
          {room.players.map((p) => (
            <SeatView
              key={p.seat_id}
              player={p}
              isToAct={hand?.to_act_seat === p.seat_id}
              mySeatId={mySeatId}
              hostSeatId={room.host_seat_id}
            />
          ))}
        </div>
      </div>

      {hand && hand.street === 'showdown' && me?.status !== 'folded' && (
        <DeclareWinnerPanel hand={hand} players={room.players} isHost={isHost} send={send} />
      )}

      {room.phase === 'between_hands' && (
        <div className="card">
          {hand?.last_result && (
            <p className="muted">
              {hand.last_result.reason === 'fold_out' ? 'Everyone folded — ' : 'Showdown — '}
              pot awarded.
            </p>
          )}
          {me && me.stack === 0 ? (
            <RebuyModal config={room.config} send={send} />
          ) : isHost ? (
            <button className="btn btn-primary" style={{ width: '100%' }} onClick={() => send({ type: 'start_hand' })}>
              Start Next Hand
            </button>
          ) : (
            <p className="muted center-text">Waiting for the host to start the next hand…</p>
          )}
        </div>
      )}

      {hand && room.phase === 'in_hand' && hand.to_act_seat === mySeatId && (
        <ActionPanel hand={hand} config={room.config} send={send} />
      )}

      {hand && hand.action_log.length > 0 && <ActionLog log={hand.action_log} />}

      {isHost && <HostAdminPanel room={room} send={send} />}

      <div className="row" style={{ justifyContent: 'center', gap: '1.5rem' }}>
        {me && (
          <button className="link-btn" onClick={() => send({ type: 'toggle_sit_out' })}>
            {me.sit_out_next ? 'Sit Back In' : 'Sit Out Next Hand'}
          </button>
        )}
        <button className="link-btn" onClick={onLeave}>
          Leave Room
        </button>
      </div>
    </div>
  )
}

function ActionLog({ log }: { log: string[] }) {
  return (
    <div className="card">
      <h3>Recent Action</h3>
      <div className="action-log">
        {[...log].reverse().map((line, i) => (
          <div key={i} className="muted">
            {line}
          </div>
        ))}
      </div>
    </div>
  )
}

function HostAdminPanel({ room, send }: { room: RoomState; send: (payload: Record<string, unknown>) => void }) {
  const staleSeats = room.players.filter((p) => !p.connected)
  if (staleSeats.length === 0 || room.phase === 'in_hand') return null
  return (
    <div className="card">
      <h3>Host: Remove a Seat</h3>
      <p className="muted">Only works for seats disconnected long enough, and only between hands.</p>
      <div className="row wrap">
        {staleSeats.map((p) => (
          <button key={p.seat_id} className="btn" onClick={() => send({ type: 'remove_stale_seat', seat_id: p.seat_id })}>
            Remove {p.display_name}
          </button>
        ))}
      </div>
    </div>
  )
}
