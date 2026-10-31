import { useEffect, useState } from 'react'
import QRCode from 'qrcode'

export function RoomCodeCard({ code }: { code: string }) {
  const [copied, setCopied] = useState(false)
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null)

  useEffect(() => {
    const url = `${window.location.origin}${window.location.pathname}?join=${code}`
    QRCode.toDataURL(url, { margin: 1, width: 160, color: { dark: '#f0f1f3', light: '#1c2027' } })
      .then(setQrDataUrl)
      .catch(() => setQrDataUrl(null))
  }, [code])

  function copyCode() {
    navigator.clipboard?.writeText(code).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <div className="card center-text">
      <h2>{code}</h2>
      <button className="link-btn" onClick={copyCode}>
        {copied ? 'Copied' : 'Copy code'}
      </button>
      {qrDataUrl && (
        <div style={{ marginTop: '0.75rem' }}>
          <img src={qrDataUrl} width={160} height={160} alt={`QR code to join room ${code}`} style={{ borderRadius: '8px' }} />
          <p className="muted" style={{ marginTop: '0.3rem' }}>
            Scan to join
          </p>
        </div>
      )}
    </div>
  )
}
