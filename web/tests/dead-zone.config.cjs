const { defineConfig } = require('@playwright/test')
module.exports = defineConfig({ ...require('./hud.config.cjs'), testMatch: 'dead-zone.e2e.cjs' })
