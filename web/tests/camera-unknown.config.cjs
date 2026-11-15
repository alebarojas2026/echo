const { defineConfig } = require('@playwright/test')
module.exports = defineConfig({ ...require('./hud.config.cjs'), testMatch: 'camera-unknown.e2e.cjs' })
