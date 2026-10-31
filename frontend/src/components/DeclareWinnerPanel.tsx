import { useState } from 'react'
import type { HandState, Player } from '../types'

export function DeclareWinnerPanel({
  hand,
  players,
  isHost,
  send,
}: {
  hand: HandState
  players: Player[]
  isHost: boolean
  send: (payload: Record<string, unknown>) => void
}) {
  const [selections, setSelections] = useState<Record<number, number[]>>({})
  const [splitMode, setSplitMode] = useState<Record<number, boolean>>({})

  function nameFor(seatId: number): string {
    return players.find((p) => p.seat_id === seatId)?.display_name ?? `Seat ${seatId}`
  }

  function pick(potIndex: number, seatId: number) {
    setSelections((prev) => {
      if (splitMode[potIndex]) {
        const current = prev[potIndex] ?? []
        const next = current.includes(seatId) ? current.filter((s) => s !== seatId) : [...current, seatId]
        return { ...prev, [potIndex]: next }
      }
      // Single-select (default): picking a winner replaces any other pick for this pot.
      return { ...prev, [potIndex]: [seatId] }
    })
  }

  function toggleSplit(potIndex: number) {
    setSplitMode((prev) => ({ ...prev, [potIndex]: !prev[potIndex] }))
    setSelections((prev) => ({ ...prev, [potIndex]: [] }))
  }

  function submit() {
    const assignments = hand.pots.map((_, i) => ({ pot_index: i, winner_seats: selections[i] ?? [] }))
    send({ type: 'declare_winners', assignments })
  }

  const allAssigned = hand.pots.every((_, i) => (selections[i] ?? []).length > 0)

  if (!isHost) {
    return (
      <div className="card">
        <h3>🏆 Showdown</h3>
        <p className="muted">⏳ Waiting for the host (👑) to declare who won.</p>
      </div>
    )
  }

  return (
    <div className="card">
      <h3>🏆 Declare the winner</h3>
      <p className="muted">Everyone's revealed their cards — mark who won each pot.</p>
      {hand.pots.map((pot, i) => (
        <div key={i} className="card" style={{ background: 'var(--surface)', marginTop: '0.5rem' }}>
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
            <strong>
              🪙 {pot.label} — {pot.amount}
            </strong>
            {pot.eligible_seats.length > 1 && (
              <button className="link-btn" onClick={() => toggleSplit(i)}>
                {splitMode[i] ? '✕ cancel split' : '➗ split pot'}
              </button>
            )}
          </div>
          <div className="row wrap" style={{ marginTop: '0.4rem' }}>
            {pot.eligible_seats.map((seatId) => (
              <button
                key={seatId}
                className={`btn ${(selections[i] ?? []).includes(seatId) ? 'btn-primary' : ''}`}
                onClick={() => pick(i, seatId)}
              >
                {(selections[i] ?? []).includes(seatId) ? '✅ ' : ''}
                {nameFor(seatId)}
              </button>
            ))}
          </div>
        </div>
      ))}
      <button className="btn btn-primary" style={{ width: '100%', marginTop: '0.75rem' }} disabled={!allAssigned} onClick={submit}>
        🏆 Award Pot{hand.pots.length > 1 ? 's' : ''}
      </button>
    </div>
  )
}
