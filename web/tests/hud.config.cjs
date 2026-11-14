const { defineConfig } = require('@playwright/test')
const baseURL = process.env.HUD_BASE_URL || 'http://127.0.0.1:5174'
module.exports = defineConfig({
  testMatch: 'hud.e2e.cjs',
  outputDir: require('node:path').join(require('node:os').tmpdir(), 'radio-sight-test-results'),
  use: { baseURL, channel: 'chrome' },
  webServer: process.env.HUD_BASE_URL ? undefined : {
    cwd: __dirname,
    command: 'npm exec -- vite .. --host 127.0.0.1 --port 5174 --strictPort',
    url: baseURL + '/src/hud/index.html',
    reuseExistingServer: false,
  },
})
