const { defineConfig } = require('@playwright/test')
module.exports = defineConfig({ ...require('./hud.config.cjs'), testMatch: 'ask-room.e2e.cjs' })
