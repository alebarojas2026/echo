const { defineConfig } = require('@playwright/test')

module.exports = defineConfig({
  testMatch: 'hud.spec.cjs',
  outputDir: require('node:path').join(require('node:os').tmpdir(), 'radio-sight-test-results'),
  use: {
    baseURL: process.env.HUD_BASE_URL || 'http://localhost:5173',
    channel: 'chrome',
  },
})
