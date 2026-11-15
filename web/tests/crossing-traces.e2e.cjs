const {test,expect}=require('@playwright/test'),fs=require('node:fs'),path=require('node:path')
const layout=require('../../radio/layouts/gate-3.json')
for(const [width,height] of [[1920,1080],[1440,900]])test(`every crossing trace, Wi-Fi foremost at ${width}`,async({page})=>{
 await page.route('**/nodes.json',r=>r.fulfill({json:layout}));await page.setViewportSize({width,height});await page.emulateMedia({reducedMotion:'reduce'})
 await page.addInitScript(()=>{window.strokeWidths=[];const stroke=CanvasRenderingContext2D.prototype.stroke;CanvasRenderingContext2D.prototype.stroke=function(...args){if(this.canvas.closest('.signal'))window.strokeWidths.push(this.lineWidth);return stroke.apply(this,args)}})
 await page.goto('/tests/arrival-harness.html?op=1');await expect(page.locator('#room')).toHaveAttribute('data-scan','loaded',{timeout:20000});await page.getByTestId('skip-arrival').click();await page.keyboard.press('Escape')
 const primary=layout.links.find(l=>l.kind==='wifi'&&l.crosses_spot).id
 for(let i=0;i<16;i++){
  await page.evaluate(({i,layout})=>{const s=window.arrival.peek('still');window.arrival.update('still',{seq:i,t:10000+i*100,links:layout.links.map((l,j)=>({id:l.id,base_dbm:-45,dbm:-45-(i<6?0.2:j?5+j:16),drop_db:i<6?0.2:j?5+j:16,rate_hz:l.kind==='wifi'?25:5,status:'ok',why:0}))})},{i,layout});await page.waitForTimeout(100)
 }
 const strip=page.getByTestId('signal-strip'),row=strip.getByTestId('signal-row')
 await expect(row).toHaveAttribute('data-links',layout.links.map(l=>l.id).join(','));await expect(row).toHaveAttribute('data-primary',primary)
 await expect(strip.getByTestId('signal-value')).toHaveText('−16.0 dB')
 // The presence line's number is said once, in its own row: the Wi-Fi line above it steps out and a person is never a weak link.
 await expect(page.getByTestId('wifi-line')).toBeHidden()
 expect(await page.evaluate(()=>[...new Set(window.strokeWidths)])).toEqual(expect.arrayContaining([4,1.5]))
 if(process.env.HUD_SCREENSHOTS){fs.mkdirSync(process.env.HUD_SCREENSHOTS,{recursive:true});await page.screenshot({path:path.join(process.env.HUD_SCREENSHOTS,`${width}-crossing.png`)})}
 await page.evaluate(primary=>{const s=window.arrival.peek('still');window.arrival.update('still',{seq:50,t:13000,links:s.links.filter(l=>l.id!==primary)})},primary)
 await expect(strip.getByTestId('signal-value')).toHaveText('no signal');await expect(page.getByTestId('wifi-line')).toBeHidden()
})
