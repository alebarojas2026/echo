const { defineConfig } = require('@playwright/test')
module.exports = defineConfig({ ...require('./hud.config.cjs'), testMatch: 'presence.e2e.cjs' })
