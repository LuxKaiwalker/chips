import type { HandState } from '../types'

export function PotDisplay({ hand }: { hand: HandState }) {
  return (
    <div className="card pot-display">
      <div className="muted">Pot</div>
      <div className="total">{hand.total_pot}</div>
      {hand.pots.length > 1 && (
        <div className="sidepots">
          {hand.pots.map((pot) => (
            <span key={pot.label} className="badge">
              {pot.label}: {pot.amount}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
