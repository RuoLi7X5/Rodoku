import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // AutoDL/反向代理访问 Vite dev server 时，Host 会变成外网域名；
    // 不放开会触发 “Blocked request. This host ... is not allowed.”
    allowedHosts: 'all',
  },
})


