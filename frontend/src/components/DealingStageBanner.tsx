import type { HandState } from '../types'
import { STREET_CARD_COUNT, STREET_DEAL_LABEL } from '../types'

export function DealingStageBanner({
  hand,
  myStatus,
  onAdvance,
}: {
  hand: HandState
  myStatus: string
  onAdvance: () => void
}) {
  const revealed = STREET_CARD_COUNT[hand.street]
  // Only a player still in the hand confirms the deal; the server rejects
  // anyone folded, sitting out or busted.
  const canAdvance = myStatus === 'active' || myStatus === 'all_in'

  return (
    <div className="stage-banner" key={hand.street}>
      <div className="board-slots">
        {Array.from({ length: 5 }, (_, i) => (
          <span key={i} className={`board-slot ${i < revealed ? 'lit' : ''}`} style={{ animationDelay: `${i * 0.08}s` }} />
        ))}
      </div>
      <div className="stage-label">{STREET_DEAL_LABEL[hand.street]}</div>
      {hand.awaiting_runout_confirmation && canAdvance && (
        <button className="btn btn-primary" style={{ marginTop: '0.5rem' }} onClick={onAdvance}>
          Dealt — continue
        </button>
      )}
      {hand.awaiting_runout_confirmation && !canAdvance && (
        <p className="muted">Waiting for another player to confirm the deal…</p>
      )}
    </div>
  )
}
