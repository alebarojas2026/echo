const { defineConfig } = require('@playwright/test')
const baseURL = process.env.HUD_BASE_URL || 'http://localhost:5173'
module.exports = defineConfig({
  testMatch: 'hud.spec.cjs',
  outputDir: require('node:path').join(require('node:os').tmpdir(), 'radio-sight-test-results'),
  use: { baseURL, channel: 'chrome' },
  webServer: process.env.HUD_BASE_URL ? undefined : {
    cwd: __dirname,
    command: 'npm exec -- vite .. --host --strictPort',
    url: baseURL + '/src/hud/',
    reuseExistingServer: true,
  },
})
