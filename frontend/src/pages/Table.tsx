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
}: {
  room: RoomState
  mySeatId: number
  send: (payload: Record<string, unknown>) => void
}) {
  const hand = room.hand
  const me = room.players.find((p) => p.seat_id === mySeatId)
  const isHost = mySeatId === room.host_seat_id

  return (
    <div className="screen">
      <div className="card center-text">
        <span className="muted">Room {room.code}</span>
        {hand && <h3>Hand #{hand.hand_number}</h3>}
      </div>

      {hand && <DealingStageBanner hand={hand} myStatus={me?.status ?? ''} onAdvance={() => send({ type: 'advance_runout' })} />}
      {hand && <PotDisplay hand={hand} />}

      <div className="card">
        <div className="seat-list">
          {room.players.map((p) => (
            <SeatView key={p.seat_id} player={p} isToAct={hand?.to_act_seat === p.seat_id} mySeatId={mySeatId} />
          ))}
        </div>
      </div>

      {hand && hand.street === 'showdown' && me?.status !== 'folded' && (
        <DeclareWinnerPanel hand={hand} players={room.players} send={send} />
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
          ) : (
            <button className="btn btn-primary" style={{ width: '100%' }} onClick={() => send({ type: 'start_hand' })}>
              Start Next Hand
            </button>
          )}
        </div>
      )}

      {hand && room.phase === 'in_hand' && hand.to_act_seat === mySeatId && (
        <ActionPanel hand={hand} config={room.config} send={send} />
      )}

      {isHost && (
        <HostAdminPanel room={room} send={send} />
      )}
    </div>
  )
}

function HostAdminPanel({ room, send }: { room: RoomState; send: (payload: Record<string, unknown>) => void }) {
  const staleSeats = room.players.filter((p) => !p.connected)
  if (staleSeats.length === 0 || room.phase === 'in_hand') return null
  return (
    <div className="card">
      <h3>Host: remove a seat</h3>
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
