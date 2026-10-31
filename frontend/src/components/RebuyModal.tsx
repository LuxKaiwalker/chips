import { useState } from 'react'
import type { RoomConfig } from '../types'

export function RebuyModal({ config, send }: { config: RoomConfig; send: (payload: Record<string, unknown>) => void }) {
  const [amount, setAmount] = useState(config.starting_stack)

  return (
    <div className="card">
      <h3>You're out of chips</h3>
      <p className="muted">Rebuy to keep playing. This is trust-based, same as buying more chips at the table.</p>
      <div className="field">
        <label>Rebuy amount</label>
        <input type="number" min={1} value={amount} onChange={(e) => setAmount(Number(e.target.value))} />
      </div>
      <button className="btn btn-primary" style={{ width: '100%' }} onClick={() => send({ type: 'rebuy', amount })}>
        Rebuy {amount} chips
      </button>
    </div>
  )
}
