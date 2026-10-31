import { useState } from 'react'
import type { HandState, Player } from '../types'

export function DeclareWinnerPanel({
  hand,
  players,
  send,
}: {
  hand: HandState
  players: Player[]
  send: (payload: Record<string, unknown>) => void
}) {
  const [selections, setSelections] = useState<Record<number, number[]>>({})

  function nameFor(seatId: number): string {
    return players.find((p) => p.seat_id === seatId)?.display_name ?? `Seat ${seatId}`
  }

  function toggle(potIndex: number, seatId: number) {
    setSelections((prev) => {
      const current = prev[potIndex] ?? []
      const next = current.includes(seatId) ? current.filter((s) => s !== seatId) : [...current, seatId]
      return { ...prev, [potIndex]: next }
    })
  }

  function submit() {
    const assignments = hand.pots.map((_, i) => ({ pot_index: i, winner_seats: selections[i] ?? [] }))
    send({ type: 'declare_winners', assignments })
  }

  const allAssigned = hand.pots.every((_, i) => (selections[i] ?? []).length > 0)

  return (
    <div className="card">
      <h3>Declare the winner</h3>
      <p className="muted">Everyone's revealed their cards. Any player can mark who won each pot.</p>
      {hand.pots.map((pot, i) => (
        <div key={i} className="card" style={{ background: 'var(--surface)', marginTop: '0.5rem' }}>
          <strong>
            {pot.label} — {pot.amount} chips
          </strong>
          <div className="row wrap" style={{ marginTop: '0.4rem' }}>
            {pot.eligible_seats.map((seatId) => (
              <button
                key={seatId}
                className={`btn ${(selections[i] ?? []).includes(seatId) ? 'btn-primary' : ''}`}
                onClick={() => toggle(i, seatId)}
              >
                {nameFor(seatId)}
              </button>
            ))}
          </div>
        </div>
      ))}
      <button className="btn btn-primary" style={{ width: '100%', marginTop: '0.75rem' }} disabled={!allAssigned} onClick={submit}>
        Award Pot{hand.pots.length > 1 ? 's' : ''}
      </button>
    </div>
  )
}
