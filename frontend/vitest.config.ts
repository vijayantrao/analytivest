import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Unit and component tests (npm test). Runs in a simulated browser (jsdom); no backend needed.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
