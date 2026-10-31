import { useEffect, useState } from 'react'
import type { HandState, RoomConfig } from '../types'

export function ActionPanel({
  hand,
  config,
  send,
}: {
  hand: HandState
  config: RoomConfig
  send: (payload: Record<string, unknown>) => void
}) {
  const legal = hand.legal_actions
  const [amount, setAmount] = useState(legal?.min_to ?? 0)
  const [showRaise, setShowRaise] = useState(false)

  useEffect(() => {
    setAmount(legal?.min_to ?? 0)
    setShowRaise(false)
  }, [hand.to_act_seat, hand.street])

  if (!legal) return null

  const min = legal.min_to ?? 0
  const max = legal.max_to ?? 0

  function presetAmounts(): number[] {
    return config.raise_presets
      .map((frac) => Math.round(hand.current_bet + frac * hand.total_pot))
      .map((v) => Math.min(Math.max(v, min), max))
  }

  return (
    <div className="action-panel">
      {showRaise && legal.can_bet_or_raise && (
        <div className="card">
          <div className="raise-presets">
            {presetAmounts().map((v, i) => (
              <button key={i} className="btn" onClick={() => setAmount(v)}>
                {Math.round(config.raise_presets[i] * 100)}% pot
              </button>
            ))}
            <button className="btn" onClick={() => setAmount(max)}>
              🔥 All-in
            </button>
          </div>
          <div className="slider-row">
            <input
              type="range"
              min={min}
              max={max}
              value={amount}
              onChange={(e) => setAmount(Number(e.target.value))}
            />
            <span className="amount-display">🪙{amount}</span>
          </div>
          <button
            className="btn btn-raise"
            style={{ width: '100%', marginTop: '0.5rem' }}
            onClick={() => {
              if (amount >= max && !window.confirm(`Go all-in for ${amount}?`)) return
              send({ type: 'player_action', action: legal.action_label, amount })
            }}
          >
            {legal.action_label === 'bet' ? '⬆️ Bet' : '⬆️ Raise to'} 🪙{amount}
          </button>
        </div>
      )}

      <div className="action-buttons">
        <button className="btn btn-fold" onClick={() => send({ type: 'player_action', action: 'fold' })}>
          🚫 Fold
        </button>
        {legal.can_check && (
          <button className="btn btn-check-call" onClick={() => send({ type: 'player_action', action: 'check' })}>
            ✓ Check
          </button>
        )}
        {legal.can_call && (
          <button className="btn btn-check-call" onClick={() => send({ type: 'player_action', action: 'call' })}>
            ✓ Call 🪙{legal.call_amount}
          </button>
        )}
        {legal.can_bet_or_raise && (
          <button className="btn btn-raise" onClick={() => setShowRaise((v) => !v)}>
            {legal.action_label === 'bet' ? '⬆️ Bet' : '⬆️ Raise'}
          </button>
        )}
      </div>
    </div>
  )
}
