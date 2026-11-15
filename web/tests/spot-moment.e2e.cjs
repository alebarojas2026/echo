const {test,expect}=require('@playwright/test'),fs=require('node:fs'),path=require('node:path')
const layout=require('../../radio/layouts/gate-3.json')
for(const [width,height] of [[1920,1080],[1440,900]])test(`three spot headlines from board state at ${width}`,async({page})=>{
 await page.route('**/nodes.json',r=>r.fulfill({json:layout}));await page.setViewportSize({width,height});await page.emulateMedia({reducedMotion:'reduce'})
 await page.goto('/tests/arrival-harness.html?op=1');await expect(page.locator('#room')).toHaveAttribute('data-scan','loaded',{timeout:20000});await page.getByTestId('skip-arrival').click();await page.keyboard.press('Escape')
 for(const [scene,text] of [['moving','Someone is here, moving'],['still','Someone is here, standing still'],['object','Something was left in the Wi-Fi line']]){
  const update = () => page.evaluate(({scene,layout})=>{const s=window.arrival.peek(scene==='object'?'object':'still');window.arrival.update(scene==='object'?'object':'still',{pred:{...s.pred,motion:scene==='object'?null:scene},advice:null,links:layout.links.map(l=>({id:l.id,dbm:-61,base_dbm:-45,drop_db:16,status:'ok',rate_hz:25,why:0}))})},{scene,layout})
  await update();await page.waitForTimeout(450);await update();await page.waitForTimeout(200)
  await expect(page.getByTestId('judge-headline')).toHaveText(text)
  if(scene==='object')await expect(page.getByTestId('judge-detail')).toHaveText('−16.0 dB')
  await expect(page.getByTestId('judge-headline')).toBeInViewport({ratio:1})
  if(process.env.HUD_SCREENSHOTS){fs.mkdirSync(process.env.HUD_SCREENSHOTS,{recursive:true});await page.screenshot({path:path.join(process.env.HUD_SCREENSHOTS,`${width}-${scene}.png`)})}
 }
})
