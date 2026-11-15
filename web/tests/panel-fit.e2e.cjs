const {test,expect}=require('@playwright/test')
const fs=require('node:fs'),path=require('node:path')
const layout=require('./fixtures/gate-layout.json')
for(const [width,height] of [[1920,1080],[1440,900]])test(`full proof and cards fit at ${width}`,async({page})=>{
 await page.route('**/nodes.json',r=>r.fulfill({json:layout}))
 await page.route('**/proof.json',r=>r.fulfill({json:{presence:{correct:19,total:20,always_empty_correct:10},zone:{correct:19,total:20},person_vs_object:{correct:18,total:20},train_s:31,ms_per_decision:{p50:24},watts:{radio_only:6},bytes_out:0,images_stored:0,models_on_board:3}}))
 await page.setViewportSize({width,height});await page.emulateMedia({reducedMotion:'reduce'})
 await page.goto('/tests/arrival-harness.html?op=1');await expect(page.locator('#room')).toHaveAttribute('data-scan','loaded',{timeout:20000});await page.getByTestId('skip-arrival').click();await page.keyboard.press('Escape')
 await page.evaluate(()=>window.arrival.update('still',{alert:{state:'check_on',zone:1,still_s:13,limit_s:10}}))
 await expect(page.locator('#hud footer dl > div:visible')).toHaveCount(9)
 const check=async()=>{
  for(const selector of ['#hud > header','#hud .privacy-line','.stillness-card','#hud > .signal','#hud footer'])await expect(page.locator(selector)).toBeInViewport({ratio:1})
  const footer=await page.locator('#hud footer').boundingBox(),signal=await page.locator('#hud > .signal').boundingBox();expect(signal.y+signal.height).toBeLessThanOrEqual(footer.y+1)
 }
 await check()
 const shot=async name=>{if(process.env.HUD_SCREENSHOTS){fs.mkdirSync(process.env.HUD_SCREENSHOTS,{recursive:true});await page.screenshot({path:path.join(process.env.HUD_SCREENSHOTS,`${width}-${name}.png`)})}}
 await shot('all-proof')
 await page.evaluate(()=>window.arrival.update('blind',{armed:true,tamper:['pi5b']}))
 await expect(page.getByTestId('judge-headline')).toBeVisible();await expect(page.locator('#hud > header')).toBeInViewport({ratio:1});await expect(page.locator('#hud .privacy-line')).toBeInViewport({ratio:1})
 const privacy=await page.locator('#hud .privacy-line').boundingBox(),tamper=await page.getByTestId('judge-headline').boundingBox();expect(tamper.y).toBeGreaterThanOrEqual(privacy.y+privacy.height)
 await shot('tamper')
})
