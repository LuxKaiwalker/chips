import { useState } from 'react'
import { ApiError, submitPassphrase } from '../api/http'

export function PassphraseGate({ onSuccess }: { onSuccess: () => void }) {
  const [passphrase, setPassphrase] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await submitPassphrase(passphrase)
      onSuccess()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="screen">
      <div className="card" style={{ marginTop: '3rem' }}>
        <h1>🂡 Chips</h1>
        <p className="muted">Enter tonight's passphrase to join the table.</p>
        <form onSubmit={submit}>
          <div className="field">
            <label>Passphrase</label>
            <input
              type="password"
              autoFocus
              value={passphrase}
              onChange={(e) => setPassphrase(e.target.value)}
            />
          </div>
          {error && <div className="error-banner">{error}</div>}
          <button className="btn btn-primary" type="submit" disabled={busy || !passphrase} style={{ width: '100%' }}>
            Enter
          </button>
        </form>
      </div>
    </div>
  )
}
