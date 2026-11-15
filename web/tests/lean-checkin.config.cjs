const {defineConfig}=require('@playwright/test')
module.exports=defineConfig({testDir:'.',outputDir:'../../test-results',testMatch:['lean-checkin.e2e.cjs','stillness.e2e.cjs'],workers:1,use:{baseURL:process.env.HUD_BASE_URL||'http://127.0.0.1:5173',browserName:'chromium',channel:'chrome',headless:true},timeout:30000})


