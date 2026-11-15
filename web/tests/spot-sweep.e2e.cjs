const {test,expect}=require('@playwright/test')
const fs=require('node:fs'),path=require('node:path')
const gate=require('./fixtures/gate-layout.json')
const layout={...gate,links:gate.links.map(l=>({...l,crosses_spot:l.id==='pi5>pi5b:wifi'||l.crosses_spot}))}
for(const [width,height] of [[1920,1080],[1440,900]])test(`one-spot judge words across states at ${width}`,async({page})=>{
 await page.route('**/nodes.json',r=>r.fulfill({json:layout}));await page.setViewportSize({width,height});await page.emulateMedia({reducedMotion:'reduce'})
 await page.goto('/tests/arrival-harness.html?op=1');await expect(page.locator('#room')).toHaveAttribute('data-scan','loaded',{timeout:20000});await page.getByTestId('skip-arrival').click();await page.keyboard.press('Escape')
 for(const name of ['empty','still','camera','between','object','blind','checkin']){
  await page.evaluate(name=>window.arrival.update(name),name)
  expect(await page.locator('body').innerText()).not.toMatch(/\b(on the left|on the right|beacons?|five devices|five nodes|twelve links|zone [12])\b/i)
  if(process.env.HUD_SCREENSHOTS&&['empty','still','blind'].includes(name)){fs.mkdirSync(process.env.HUD_SCREENSHOTS,{recursive:true});await page.screenshot({path:path.join(process.env.HUD_SCREENSHOTS,`${width}-${name}.png`)})}
 }
 await page.evaluate(()=>{const s=window.arrival.peek('still');window.arrival.update('still',{alert:{...s.alert,state:'none'},advice:{id:'move',link:'pi5>pi5b:wifi',move_m:[-0.3,0],to_spot:'S-W30',before_dbm:-65,after_dbm:null,text:'Move the router',cause:'blocked',near:'pi5b',xy_m:[0,0],why:[]}})})
 await expect(page.getByTestId('advice-text')).toContainText('30 cm west')
 expect(await page.locator('body').innerText()).not.toMatch(/\b(left|right|beacons?|five devices|zone [12])\b/i)
 if(process.env.HUD_SCREENSHOTS)await page.screenshot({path:path.join(process.env.HUD_SCREENSHOTS,`${width}-advice.png`)})
})
