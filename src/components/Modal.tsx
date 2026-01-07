import { useEffect } from 'react'

export function Modal({
  title,
  open,
  onClose,
  children,
}: {
  title: string
  open: boolean
  onClose: () => void
  children: React.ReactNode
}) {
  useEffect(() => {
    if (!open) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="modalOverlay" role="dialog" aria-modal="true" aria-label={title}>
      <div className="modalPanel">
        <div className="modalHeader">
          <div className="modalTitle">{title}</div>
          <button type="button" className="iconBtn" onClick={onClose} aria-label="关闭" title="关闭">
            ✕
          </button>
        </div>
        <div className="modalBody">{children}</div>
      </div>
      <button type="button" className="modalBackdrop" aria-label="关闭弹窗" onClick={onClose} />
    </div>
  )
}




