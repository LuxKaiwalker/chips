import type { HandState } from '../types'
import { STREET_DEAL_LABEL } from '../types'

export function DealingStageBanner({
  hand,
  myStatus,
  onAdvance,
}: {
  hand: HandState
  myStatus: string
  onAdvance: () => void
}) {
  return (
    <div className="stage-banner">
      <div>{STREET_DEAL_LABEL[hand.street]}</div>
      {hand.awaiting_runout_confirmation && myStatus !== 'folded' && (
        <button className="btn btn-primary" style={{ marginTop: '0.5rem' }} onClick={onAdvance}>
          Dealt it — continue
        </button>
      )}
      {hand.awaiting_runout_confirmation && myStatus === 'folded' && (
        <p className="muted">Waiting for another player to confirm the deal…</p>
      )}
    </div>
  )
}
