import { useState } from 'react'
import { ApiError, createRoom, joinRoom } from '../api/http'

export function Home({
  onEnterRoom,
  initialJoinCode,
}: {
  onEnterRoom: (code: string) => void
  initialJoinCode?: string | null
}) {
  const [mode, setMode] = useState<'create' | 'join'>(initialJoinCode ? 'join' : 'create')
  const [displayName, setDisplayName] = useState('')
  const [smallBlind, setSmallBlind] = useState(1)
  const [bigBlind, setBigBlind] = useState(2)
  const [startingStack, setStartingStack] = useState(200)
  const [rotateDealer, setRotateDealer] = useState(false)
  const [joinCode, setJoinCode] = useState(initialJoinCode ?? '')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const res = await createRoom({
        display_name: displayName,
        small_blind: smallBlind,
        big_blind: bigBlind,
        starting_stack: startingStack,
        raise_presets: [0.33, 0.5, 0.75, 1.0],
        rotate_dealer: rotateDealer,
      })
      onEnterRoom(res.room_code)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create room')
    } finally {
      setBusy(false)
    }
  }

  async function handleJoin(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const res = await joinRoom(joinCode.trim(), displayName)
      onEnterRoom(res.room_code)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not join room')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="screen">
      <h1>Chips</h1>
      <div className="card">
        <div className="row" style={{ marginBottom: '1rem' }}>
          <button className={`btn ${mode === 'create' ? 'btn-primary' : ''}`} style={{ flex: 1 }} onClick={() => setMode('create')}>
            Create
          </button>
          <button className={`btn ${mode === 'join' ? 'btn-primary' : ''}`} style={{ flex: 1 }} onClick={() => setMode('join')}>
            Join
          </button>
        </div>

        {mode === 'create' ? (
          <form onSubmit={handleCreate}>
            <div className="field">
              <label>Your name</label>
              <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} required />
            </div>
            <div className="field">
              <label>Small blind</label>
              <input type="number" min={1} value={smallBlind} onChange={(e) => setSmallBlind(Number(e.target.value))} />
            </div>
            <div className="field">
              <label>Big blind</label>
              <input type="number" min={1} value={bigBlind} onChange={(e) => setBigBlind(Number(e.target.value))} />
            </div>
            <div className="field">
              <label>Starting stack (per player)</label>
              <input type="number" min={1} value={startingStack} onChange={(e) => setStartingStack(Number(e.target.value))} />
            </div>
            <div className="field">
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <input type="checkbox" checked={rotateDealer} onChange={(e) => setRotateDealer(e.target.checked)} />
                Rotate dealer duties each hand
              </label>
            </div>
            {error && <div className="error-banner">{error}</div>}
            <button className="btn btn-primary" type="submit" disabled={busy} style={{ width: '100%' }}>
              Create Room
            </button>
          </form>
        ) : (
          <form onSubmit={handleJoin}>
            <div className="field">
              <label>Your name</label>
              <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} required />
            </div>
            <div className="field">
              <label>Room code</label>
              <input
                value={joinCode}
                onChange={(e) => setJoinCode(e.target.value.replace(/\D/g, ''))}
                inputMode="numeric"
                pattern="[0-9]*"
                style={{ letterSpacing: '0.2em' }}
                maxLength={6}
                required
              />
            </div>
            {error && <div className="error-banner">{error}</div>}
            <button className="btn btn-primary" type="submit" disabled={busy} style={{ width: '100%' }}>
              Join Room
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
