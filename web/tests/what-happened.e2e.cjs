const {test,expect}=require('@playwright/test'),fs=require('node:fs'),path=require('node:path')
const layout=require('../../radio/layouts/gate.json')
const answer={answer:'At 06:01 someone arrived. At 06:03 they left.',rows:[{row:'sentence',at:'06:01',t:1763186460000,text:'Someone arrived.',cites:[4012]},{row:'sentence',at:'06:03',t:1763186580000,text:'They left the spot.',cites:[4040]},{row:'chain',ok:true}],tool:'story',ms:15,steps:[{tool:'fetch events',ms:1,rows:2},{tool:'fetch summaries',ms:12,rows:61},{tool:'line up the timeline',ms:0.2,rows:2},{tool:'verify the chain',ms:3,rows:61},{tool:'write the story',ms:0.1,rows:2}],cites:[4012,4040],chain_ok:true}
for(const [width,height] of [[1920,1080],[1440,900]])test(`one tap timeline, failed chain and older board at ${width}`,async({page})=>{
 await page.route('**/nodes.json',r=>r.fulfill({json:layout}));await page.setViewportSize({width,height});await page.emulateMedia({reducedMotion:'reduce'})
 let response=answer,requests=[]
 await page.route('**/ask',async r=>{requests.push(r.request().postDataJSON());await r.fulfill({json:response})})
 await page.goto('/tests/arrival-harness.html?op=1&ask=board');await expect(page.locator('#room')).toHaveAttribute('data-scan','loaded',{timeout:30000})
 await expect(page.getByTestId('arrival-claim')).toHaveText('A witness that never watches.')
 await page.keyboard.press('Escape')
 await page.getByTestId('arrival-what-happened').click();await expect(page.locator('.story-timeline li')).toHaveCount(2)
 expect(requests).toEqual([{question:'what happened in the last five minutes'}]);requests=[]
 await page.keyboard.press('Escape');await page.keyboard.press('o');await page.getByTestId('skip-arrival').click();await page.keyboard.press('Escape')
 await page.evaluate(()=>window.arrival.update('empty',{model:{trained:false,ver:null},teacher:null,cam:'off',baseline:{state:'idle'}}))
 expect(await page.locator('body').innerText()).not.toMatch(/camera|lesson/i)
 await page.evaluate(()=>window.arrival.update('empty',{cam:'on',model:{trained:false,training:{lesson:{started_t:1000,agree:3,of:10}}}}))
 await expect(page.getByTestId('cam-status')).toBeHidden();await expect(page.getByTestId('lesson-status')).toBeHidden();await expect(page.getByTestId('handoff-strip')).toBeHidden()
 await page.evaluate(()=>window.arrival.update('empty',{cam:'off',model:{trained:false,ver:null},teacher:null}))
 const shot=async name=>{if(process.env.HUD_SCREENSHOTS){fs.mkdirSync(process.env.HUD_SCREENSHOTS,{recursive:true});await page.screenshot({path:path.join(process.env.HUD_SCREENSHOTS,`${width}-${name}.png`)})}}
 await page.getByTestId('what-happened').click()
 await expect(page.locator('.story-timeline li')).toHaveCount(2);expect(requests).toEqual([{question:'what happened in the last five minutes'}])
 await expect(page.getByLabel('Your question')).toBeHidden();await expect(page.locator('.story-timeline time').first()).toHaveText('06:01')
 await expect(page.locator('.story-steps')).toContainText('fetch summaries · 12 ms · 61 rows');await expect(page.locator('.story-cites')).toHaveText('Cited records: 4012, 4040')
 await expect(page.locator('.story-cites')).toBeInViewport({ratio:1});expect(await page.locator('.ask-story *').evaluateAll(es=>es.every(e=>parseFloat(getComputedStyle(e).fontSize)>=28))).toBe(true);await shot('timeline')
 await page.keyboard.press('Escape');response={...answer,chain_ok:false,answer:'Warning: record 4012 does not verify. '+answer.answer}
 await page.getByTestId('what-happened').click();await expect(page.locator('.ask-story > :first-child')).toHaveText('Warning: record 4012 does not verify.')
 expect(await page.locator('.story-warning').evaluate(e=>{const probe=document.createElement('span');probe.style.color='var(--fault)';e.append(probe);const same=getComputedStyle(e).color===getComputedStyle(probe).color;probe.remove();return same})).toBe(true)
 await expect(page.locator('.story-warning')).toHaveAttribute('role','alert');await shot('fault')
 await page.keyboard.press('Escape');response={answer:'No events in the last five minutes.',rows:[{seconds:300}],tool:'presence',ms:3}
 await page.getByTestId('what-happened').click();await expect(page.getByTestId('ask-answer')).toHaveText(response.answer);await expect(page.getByTestId('ask-story')).toBeHidden();await expect(page.locator('.ask-evidence')).toBeHidden();await shot('older-board')
})
