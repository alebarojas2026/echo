const { defineConfig } = require('@playwright/test')
module.exports = defineConfig({ ...require('./hud.config.cjs'), testMatch: 'tamper.e2e.cjs' })
