const {defineConfig}=require('@playwright/test')
module.exports=defineConfig({...require('./hud.config.cjs'),testMatch:['lean-checkin.e2e.cjs','stillness.e2e.cjs']})
