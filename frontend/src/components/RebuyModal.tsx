import { useState } from 'react'
import type { RoomConfig } from '../types'

export function RebuyModal({ config, send }: { config: RoomConfig; send: (payload: Record<string, unknown>) => void }) {
  const max = config.starting_stack
  const [amount, setAmount] = useState(max)
  const valid = Number.isInteger(amount) && amount >= 1 && amount <= max

  return (
    <div className="card">
      <h3>You're out of chips</h3>
      <p className="muted">Rebuy to keep playing. Up to the starting stack of {max}, the same buy-in everyone sat down with.</p>
      <div className="field">
        <label>Rebuy amount</label>
        <input type="number" min={1} max={max} step={1} value={amount} onChange={(e) => setAmount(Number(e.target.value))} />
      </div>
      <button className="btn btn-primary" style={{ width: '100%' }} disabled={!valid} onClick={() => send({ type: 'rebuy', amount })}>
        {valid ? `Rebuy ${amount} chips` : `Enter 1 to ${max}`}
      </button>
    </div>
  )
}
