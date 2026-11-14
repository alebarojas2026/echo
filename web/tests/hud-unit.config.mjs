import { defineConfig } from '../node_modules/vitest/dist/config.js'
export default defineConfig({ test: { include: ['src/hud/**/*.test.ts'] } })
