import { HashRouter, Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import App from './App'
import { RodokuPage } from './rodoku/RodokuPage'
import { VizPage } from './viz/VizPage'

function FloatingNav() {
  const loc = useLocation()
  const isRank = loc.pathname === '/rank' || loc.pathname === '/'
  const isRodoku = loc.pathname === '/rodoku'
  const isViz = loc.pathname === '/viz'

  return (
    <div
      style={{
        position: 'fixed',
        top: 10,
        right: 10,
        zIndex: 9999,
        display: 'flex',
        gap: 8,
      }}
    >
      <Link
        to="/rank"
        style={{
          padding: '6px 10px',
          borderRadius: 10,
          border: '1px solid #d0d5dd',
          background: isRank ? '#eff8ff' : '#fff',
          color: '#101828',
          textDecoration: 'none',
          fontWeight: 800,
          fontSize: 12,
        }}
      >
        秩页面
      </Link>
      <Link
        to="/rodoku"
        style={{
          padding: '6px 10px',
          borderRadius: 10,
          border: '1px solid #d0d5dd',
          background: isRodoku ? '#ecfdf3' : '#fff',
          color: '#101828',
          textDecoration: 'none',
          fontWeight: 800,
          fontSize: 12,
        }}
      >
        Rodoku
      </Link>
      <Link
        to="/viz"
        style={{
          padding: '6px 10px',
          borderRadius: 10,
          border: '1px solid #d0d5dd',
          background: isViz ? '#f4f3ff' : '#fff',
          color: '#101828',
          textDecoration: 'none',
          fontWeight: 800,
          fontSize: 12,
        }}
      >
        可视化
      </Link>
    </div>
  )
}

export default function Root() {
  return (
    <HashRouter>
      <FloatingNav />
      <Routes>
        <Route path="/" element={<Navigate to="/rank" replace />} />
        <Route path="/rank" element={<App />} />
        <Route path="/rodoku" element={<RodokuPage />} />
        <Route path="/viz" element={<VizPage />} />
        <Route path="*" element={<Navigate to="/rank" replace />} />
      </Routes>
    </HashRouter>
  )
}

