export function SvgIcon({
  children,
  viewBox = '0 0 24 24',
}: {
  children: React.ReactNode
  viewBox?: string
}) {
  return (
    <svg width="18" height="18" viewBox={viewBox} fill="none" xmlns="http://www.w3.org/2000/svg">
      {children}
    </svg>
  )
}

export function IconImport() {
  return (
    <SvgIcon>
      <path
        d="M12 3v10m0 0 4-4m-4 4-4-4M5 17v3h14v-3"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </SvgIcon>
  )
}

export function IconExport() {
  return (
    <SvgIcon>
      <path
        d="M12 21V11m0 0 4 4m-4-4-4 4M5 7V4h14v3"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </SvgIcon>
  )
}

export function IconImage() {
  return (
    <SvgIcon>
      <path
        d="M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6Z"
        stroke="currentColor"
        strokeWidth="2"
      />
      <path
        d="M8.5 10.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z"
        stroke="currentColor"
        strokeWidth="2"
      />
      <path
        d="M20 16l-5-5-6 6"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </SvgIcon>
  )
}

export function IconCandidates() {
  return (
    <SvgIcon>
      <path
        d="M4 4h7v7H4V4Zm9 0h7v7h-7V4ZM4 13h7v7H4v-7Zm9 0h7v7h-7v-7Z"
        stroke="currentColor"
        strokeWidth="2"
      />
    </SvgIcon>
  )
}

export function IconSparkle() {
  return (
    <SvgIcon>
      <path
        d="M12 2l1.2 4.2L17.4 8 13.2 9.2 12 13.4 10.8 9.2 6.6 8l4.2-1.8L12 2Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <path
        d="M5 14l.7 2.4L8 17.4l-2.3 1L5 21l-.7-2.6L2 17.4l2.3-1L5 14Zm14 1 .6 2.1 2.4.9-2.4.9L19 21l-.6-2.1-2.4-.9 2.4-.9L19 15Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
      />
    </SvgIcon>
  )
}

export function IconTrash() {
  return (
    <SvgIcon>
      <path
        d="M6 7h12M10 7V5h4v2m-7 0 1 14h8l1-14"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </SvgIcon>
  )
}




