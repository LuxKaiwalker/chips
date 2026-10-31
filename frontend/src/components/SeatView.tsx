import type { Player } from '../types'

export function SeatView({ player, isToAct, mySeatId }: { player: Player; isToAct: boolean; mySeatId: number }) {
  const classes = ['seat']
  if (isToAct) classes.push('to-act')
  if (player.status === 'folded') classes.push('folded')
  if (!player.connected) classes.push('disconnected')

  return (
    <div className={classes.join(' ')}>
      <span>
        {player.display_name}
        {player.is_button && <span className="badge button">BTN</span>}
        {player.seat_id === mySeatId && <span className="badge">you</span>}
        {player.status === 'all_in' && <span className="badge allin">all-in</span>}
        {player.status === 'sitting_out' && <span className="badge">sitting out</span>}
        {!player.connected && <span className="badge">disconnected</span>}
      </span>
      <span>
        {player.contrib_street > 0 && <span className="muted" style={{ marginRight: '0.6rem' }}>bet {player.contrib_street}</span>}
        <strong>{player.stack}</strong>
      </span>
    </div>
  )
}
