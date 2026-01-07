export function IconButton({
  icon,
  label,
  tip,
  onClick,
  disabled,
  pressed,
}: {
  icon: React.ReactNode
  label: string
  tip: string
  onClick?: () => void
  disabled?: boolean
  pressed?: boolean
}) {
  return (
    <button
      type="button"
      className={'iconBtn' + (pressed ? ' isPressed' : '')}
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
    >
      <span className="icon">{icon}</span>
      <span className="tooltip" role="tooltip">
        <div className="tooltipTitle">{label}</div>
        <div className="tooltipDesc">{tip}</div>
      </span>
    </button>
  )
}




