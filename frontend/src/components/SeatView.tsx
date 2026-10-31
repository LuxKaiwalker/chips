import type { Player } from '../types'

export function SeatView({
  player,
  isToAct,
  mySeatId,
  hostSeatId,
}: {
  player: Player
  isToAct: boolean
  mySeatId: number
  hostSeatId: number
}) {
  const classes = ['seat']
  if (isToAct) classes.push('to-act')
  if (player.status === 'folded') classes.push('folded')
  if (!player.connected) classes.push('disconnected')

  return (
    <div className={classes.join(' ')}>
      <span>
        <span className={`status-dot ${player.connected ? 'connected' : 'disconnected'}`} />
        {player.display_name}
        {player.is_button && <span className="badge button">D</span>}
        {player.seat_id === hostSeatId && <span className="badge">HOST</span>}
        {player.seat_id === mySeatId && <span className="badge">YOU</span>}
        {player.status === 'all_in' && <span className="badge allin">ALL-IN</span>}
        {player.status === 'sitting_out' && <span className="badge">SITTING OUT</span>}
        {player.status === 'folded' && <span className="badge">FOLDED</span>}
        {player.status !== 'sitting_out' && player.sit_out_next && (
          <span className="badge" title="Will sit out next hand">
            NEXT: OUT
          </span>
        )}
      </span>
      <span>
        {player.contrib_street > 0 && (
          <span className="muted" style={{ marginRight: '0.6rem' }}>
            bet {player.contrib_street}
          </span>
        )}
        <strong>{player.stack}</strong>
      </span>
    </div>
  )
}
