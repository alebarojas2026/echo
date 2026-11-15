const {test,expect}=require('@playwright/test'),fs=require('node:fs'),path=require('node:path')
const layout=require('../../radio/layouts/gate.json'),chain={seq:4127,verified:true,witnesses_ok:2,witnesses:2}
for(const [width,height] of [[1920,1080],[1440,900]])test(`sealed record remains honest at ${width}`,async({page})=>{
 await page.route('**/nodes.json',r=>r.fulfill({json:layout}));await page.setViewportSize({width,height});await page.emulateMedia({reducedMotion:'reduce'})
 let calls=0,release
 await page.route('**/chain',async r=>{calls++;await new Promise(resolve=>release=resolve);await r.fulfill({json:{verified:false,first_bad_seq:4012}}).catch(()=>{})})
 await page.goto('/tests/arrival-harness.html?op=1');await expect(page.locator('#room')).toHaveAttribute('data-scan','loaded',{timeout:30000});await page.getByTestId('skip-arrival').click();await page.keyboard.press('Escape')
 const line=page.getByTestId('sealed-record'),send=async(value,stale=false)=>page.evaluate(({value,stale})=>window.arrival.update('empty',{chain:value,model:{trained:false,ver:null},teacher:null,cam:'off'},stale),{value,stale})
 const shot=async name=>{if(process.env.HUD_SCREENSHOTS){fs.mkdirSync(process.env.HUD_SCREENSHOTS,{recursive:true});await page.screenshot({path:path.join(process.env.HUD_SCREENSHOTS,`${width}-${name}.png`)})}}
 await send(undefined);await expect(line).toBeHidden();expect(calls).toBe(0);await shot('absent')
 await send(chain);await expect(line).toHaveText('Sealed record · verified · 2 witnesses');await expect(line).toHaveCSS('font-size','28px');await expect(line).toBeInViewport({ratio:1});expect(calls).toBe(0);await shot('verified')
 expect(await page.locator('body').innerText()).not.toMatch(/camera|lesson/i)
 await send({...chain,witnesses:0,witnesses_ok:0});await expect(line).toHaveText('Sealed record · verified · 0 witnesses');await expect(line).toHaveAttribute('data-tone','');await shot('no-witnesses')
 await send({...chain,verified:false});await expect(line).toContainText('verification failed');await expect.poll(()=>calls).toBe(1);release()
 await expect(line).toContainText('record 4012 failed verification');await expect(line).toHaveAttribute('data-tone','fault');await expect(line).toBeInViewport({ratio:1});await shot('fault')
 await send({...chain,seq:4128,verified:false});expect(calls).toBe(1)
 await send(chain,true);await expect(line).toHaveText('Sealed record · waiting for board')
 await send({...chain,verified:false});await expect.poll(()=>calls).toBe(2);await send(chain);release();await expect(line).toHaveText('Sealed record · verified · 2 witnesses')
 await send(undefined);await expect(line).toBeHidden()
 await page.unroute('**/chain');await page.route('**/chain',r=>r.fulfill({status:503}))
 await send({...chain,verified:false});await expect(line).toHaveText('Sealed record · verification failed · 2 witnesses')
 await page.unroute('**/chain');await page.route('**/chain',r=>r.fulfill({json:{verified:false,first_bad_seq:4000}}))
 await page.waitForTimeout(3100);await send({...chain,verified:false});await expect(line).toContainText('record 4000 failed verification')
})
