const {test,expect}=require('@playwright/test')
const fs=require('node:fs'),path=require('node:path')
require('./layout-fixture.cjs')
for(const [width,height] of [[1920,1080],[1440,900]]) test(`records follow a board ten minutes behind at ${width}`,async({page})=>{
 const spans=[]
 await page.route('**/history?*',r=>{const u=new URL(r.request().url()),from_t=+u.searchParams.get('from_t'),to_t=+u.searchParams.get('to_t');spans.push({from_t,to_t});return r.fulfill({json:{from_t,to_t,step_s:1,rows:[]}})})
 await page.setViewportSize({width,height});await page.emulateMedia({reducedMotion:'reduce'});await page.clock.install({time:new Date('2026-01-01T00:00:00Z')});await page.clock.pauseAt(new Date('2026-01-01T00:00:01Z'))
 await page.goto('/tests/arrival-harness.html?scan=0&op=1&no-state=1&records=board')
 await expect(page.getByTestId('replay-last')).toBeDisabled()
 const board=await page.evaluate(()=>{const t=Date.now()-600000;window.arrival.update('still',{t});return t})
 await expect(page.getByTestId('replay-last')).toBeEnabled()
 await page.getByTestId('skip-arrival').click();await page.keyboard.press('Escape')
 await page.getByRole('button',{name:'Ask the room',exact:true}).click()
 await page.getByRole('button',{name:'Was anyone here in the last 10 minutes?',exact:true}).click()
 await page.clock.runFor(700)
 await expect(page.getByTestId('ask-replay')).toBeVisible()
 if(process.env.HUD_SCREENSHOTS){fs.mkdirSync(process.env.HUD_SCREENSHOTS,{recursive:true});await page.screenshot({path:path.join(process.env.HUD_SCREENSHOTS,`${width}-board-time.png`)})}
 await page.getByTestId('ask-replay').click()
 await expect.poll(()=>spans.length).toBe(1)
 await page.keyboard.press('o');await page.getByTestId('replay-last').click()
 await expect.poll(()=>spans.length).toBe(2)
 for(const span of spans){expect(span.to_t).toBeGreaterThanOrEqual(board);expect(span.to_t).toBeLessThanOrEqual(board+1000);expect(span.to_t-span.from_t).toBe(120000)}
})
