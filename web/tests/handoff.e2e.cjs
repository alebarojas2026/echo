const {test,expect}=require('@playwright/test')
const fs=require('node:fs'),path=require('node:path')
require('./layout-fixture.cjs')
for(const [width,height] of [[1920,1080],[1440,900]])test(`handoff with the hall loaded at ${width}`,async({page})=>{
 await page.setViewportSize({width,height});await page.emulateMedia({reducedMotion:'reduce'})
 const open=async()=>{await page.goto('/tests/arrival-harness.html?op=1');await expect(page.locator('#room')).toHaveAttribute('data-scan','loaded',{timeout:20000});await expect(page.locator('#room')).toHaveAttribute('data-scan-file',/hall-.*\.glb/);await page.getByTestId('skip-arrival').click();await page.keyboard.press('Escape')}
 await open()
 const update=async(cam,t,training=null)=>page.evaluate(({cam,t,training})=>{const s=window.arrival.peek('still');window.arrival.update('still',{cam,t,handoff:{started_t:1000,radio_only_t:cam==='on'?null:31000},model:{...s.model,training}})},{cam,t,training})
 const shot=async name=>{if(process.env.HUD_SCREENSHOTS){fs.mkdirSync(process.env.HUD_SCREENSHOTS,{recursive:true});await page.screenshot({path:path.join(process.env.HUD_SCREENSHOTS,`${width}-${name}.png`)})}}
 await update('on',13000,{lesson:{started_t:1000,agree:6,of:10,fits:2,fitting:false}})
 await expect(page.getByTestId('handoff-title')).toHaveText('CAMERA TEACHING');await expect(page.getByTestId('handoff-detail')).toHaveText('6 of 10 agree · 2 fits');await shot('teaching')
 await update('off',31000);await expect(page.getByTestId('handoff-edge')).toBeVisible();await expect(page.getByTestId('handoff-time')).toHaveText('0:00');await shot('unplug')
 await update('off',91000);await expect(page.getByTestId('handoff-time')).toHaveText('1:00');await shot('radio')
 await open();await update('off',91000);await expect(page.getByTestId('handoff-time')).toHaveText('1:00')
 await update('unknown',92000);await expect(page.getByTestId('handoff-title')).toHaveText('CAMERA UNKNOWN');await expect(page.getByTestId('handoff-time')).toBeEmpty();await expect(page.getByTestId('handoff-edge')).toBeHidden();await shot('unknown')
})
