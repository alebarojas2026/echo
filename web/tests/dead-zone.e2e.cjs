const { test, expect } = require('@playwright/test')
const path = require('node:path')
const { layout } = require('./layout-fixture.cjs')
const shots = process.env.HUD_SCREENSHOTS
const ACTION = 'rgb(52, 178, 119)'
const TEXT = 'rgb(230, 232, 235)'
// The desk names its sides as seen on the screen; the square uses compass points.
const desk = !!layout.frame.strip_m
const way = desk ? 'left' : 'west'
const name = id => layout.nodes.find(node => node.id === id).name
const ends = desk ? `${name('pi5')} to ${name('unoq')}` : 'Pi 5 router to UNO Q'

async function open(page, width, height) {
  await page.setViewportSize({ width, height })
  await page.clock.install({ time: new Date('2026-01-01T00:00:00Z') })
  await page.clock.pauseAt(new Date('2026-01-01T00:00:01Z'))
  await page.goto('/tests/arrival-harness.html')
  await page.waitForLoadState('networkidle')
  await expect.poll(() => page.evaluate(() => !!window.arrival)).toBe(true)
  // A visitor is found first, so the arrival screen is over and the main screen shows.
  await send(page, 'still')
  await page.clock.runFor(6000)
  await expect(page.locator('.hud-arrival')).toBeHidden()
}

// One state from the mock, with the router's Wi-Fi link and the advice set the way the board would send them.
// wifiDrop: the link's drop from its baseline in dB. advice: false (none) or the fields to change.
async function send(page, scene, { wifiDrop = null, advice = null, ...rest } = {}, ms = 500) {
  await page.evaluate(([scene, wifiDrop, advice, rest]) => {
    const base = window.arrival.peek('object')
    const state = window.arrival.peek(scene)
    // The tray dims every link that passes it, so those links follow the Wi-Fi link's drop.
    const blocked = new Set(base.links.filter(link => link.drop_db >= 3).map(link => link.id).concat(base.advice.link))
    const links = state.links.map(link => !blocked.has(link.id) || wifiDrop === null ? link : { ...link, drop_db: wifiDrop, dbm: link.base_dbm - wifiDrop })
    window.arrival.update(scene, { links, advice: advice ? { ...base.advice, ...advice } : advice === false ? null : state.advice, ...rest })
  }, [scene, wifiDrop, advice, rest])
  await page.clock.runFor(ms)
}
const capture = async (page, name) => { if (shots) await page.screenshot({ path: path.join(shots, name + '.png') }) }

for (const [width, height] of [[1920, 1080], [1440, 900]]) {
  test(`a dead zone is found, the router is moved and the gain is measured, at ${width}`, async ({ page }) => {
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await open(page, width, height)
    const headline = page.getByTestId('judge-headline')
    const detail = page.getByTestId('judge-detail')
    const card = page.getByTestId('dead-zone')
    const text = page.getByTestId('advice-text')
    const line = page.getByTestId('wifi-line')

    // The link is fine: the calm line says so, and there is no card.
    await send(page, 'empty', { wifiDrop: 0.3 })
    await expect(headline).toHaveText('Nobody is here')
    await expect(page.getByTestId('wifi-word')).toHaveText('strong')
    await expect(page.getByTestId('wifi-value')).toHaveText('−0.3 dB')
    await expect(line).toHaveAttribute('aria-label', `Wi-Fi link, ${ends}`)
    await expect(card).toBeHidden()
    for (const part of await line.locator('span').all()) expect(parseFloat(await part.evaluate(el => getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(28)
    await capture(page, `${width}-1-link-ok`)

    // Something blocks it, and the board has not given advice yet: the line reads weak, still no dead zone.
    await send(page, 'object', { wifiDrop: 9.2, advice: false })
    await expect(headline).toHaveText('An object, not a person')
    await expect(page.getByTestId('wifi-word')).toHaveText('weak')
    await expect(page.getByTestId('wifi-value')).toHaveText('−9.2 dB')
    await expect(card).toBeHidden()
    await capture(page, `${width}-2-blocked`)

    // The board's advice: a dead zone, and where to move the router.
    await send(page, 'object', { wifiDrop: 9.2, advice: { before_dbm: -71.2 } })
    await expect(headline).toHaveText('Dead zone found')
    await expect(detail).toHaveText(`Something is blocking the Wi-Fi from ${ends}`)
    await expect(text).toHaveText(`Move the router 30 cm ${way}`)
    await expect(text).toHaveCSS('color', ACTION)
    await expect(page.getByTestId('before-label')).toHaveText('Wi-Fi now')
    await expect(page.getByTestId('before-dbm')).toHaveText('−71.2 dBm')
    await expect(page.getByTestId('after-dbm')).toBeHidden()
    await capture(page, `${width}-3-dead-zone-found`)

    // The router is moved: the board stops predicting and measures. The arrival screen stays away.
    const moved = { router: 'S-W30', pred: null, wifiDrop: 1.4 }
    await send(page, 'object', { ...moved, advice: { before_dbm: -71.2, after_dbm: null } })
    await expect(headline).toHaveText('Router moved')
    await expect(detail).toHaveText('Measuring the Wi-Fi at the new spot')
    await expect(text).toHaveText('Measuring…')
    await expect(text).toHaveCSS('color', TEXT)
    await expect(page.getByTestId('before-dbm')).toHaveText('−71.2 dBm')
    await expect(page.getByTestId('after-dbm')).toHaveText('__')
    await expect(page.locator('.hud-arrival')).toBeHidden()
    await capture(page, `${width}-4-measuring`)

    // The measured result: the gain, large, with the before and after it comes from.
    await send(page, 'object', { ...moved, advice: { before_dbm: -71.2, after_dbm: -63.4 } })
    await expect(headline).toHaveText('Dead zone fixed')
    await expect(detail).toHaveText(`Router moved 30 cm ${way}`)
    await expect(text).toHaveText('+7.8 dB stronger')
    await expect(text).toHaveCSS('color', ACTION)
    expect(parseFloat(await text.evaluate(el => getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(56)
    await expect(page.getByTestId('after-dbm')).toHaveText('−63.4 dBm')
    await expect(page.getByTestId('wifi-word')).toHaveText('strong')
    // Nothing spills out of the rail or off the page.
    const rail = page.locator('#hud')
    expect(await rail.evaluate(el => el.scrollHeight <= el.clientHeight && el.scrollWidth <= el.clientWidth)).toBe(true)
    const box = await text.boundingBox()
    expect(box.x + box.width).toBeLessThanOrEqual(640)
    await capture(page, `${width}-5-gain`)
    expect(errors).toEqual([])
  })
}

test('a move that did not help says so, without the action colour', async ({ page }) => {
  await open(page, 1920, 1080)
  await send(page, 'object', { router: 'S-W30', pred: null, wifiDrop: 11.3, advice: { before_dbm: -71.2, after_dbm: -73.3 } })
  await expect(page.getByTestId('judge-headline')).toHaveText('No gain at this spot')
  await expect(page.getByTestId('advice-text')).toHaveText('−2.1 dB weaker')
  await expect(page.getByTestId('advice-text')).toHaveCSS('color', TEXT)
  await expect(page.getByTestId('wifi-word')).toHaveText('weak')
})

test('the advice stays while the router is on the advised spot, and goes when it is home', async ({ page }) => {
  await open(page, 1920, 1080)
  await send(page, 'object', { wifiDrop: 9.2, advice: { before_dbm: -71.2 } })
  // A feed that drops the advice as soon as the link is clear: the screen keeps the board's last advice.
  await send(page, 'object', { router: 'S-W30', pred: null, wifiDrop: 1.4, advice: false })
  await expect(page.getByTestId('judge-headline')).toHaveText('Router moved')
  await expect(page.getByTestId('advice-text')).toHaveText('Measuring…')
  await send(page, 'empty', { wifiDrop: 0.2, advice: false })
  await expect(page.getByTestId('judge-headline')).toHaveText('Nobody is here')
  await expect(page.getByTestId('dead-zone')).toBeHidden()
})

test('the Wi-Fi line never shows a number it does not have', async ({ page }) => {
  await open(page, 1920, 1080)
  const word = page.getByTestId('wifi-word')
  const value = page.getByTestId('wifi-value')
  await page.evaluate(() => { const s = window.arrival.peek('empty'); window.arrival.update('empty', { links: s.links.map(l => ({ ...l, base_dbm: null, drop_db: null })) }) })
  await page.clock.runFor(400)
  await expect(word).toHaveText('no baseline yet')
  await page.evaluate(() => { const s = window.arrival.peek('empty'); window.arrival.update('empty', { links: s.links.map(l => ({ ...l, status: 'stale', rate_hz: 0 })) }) })
  await page.clock.runFor(400)
  await expect(word).toHaveText('no signal')
  await expect(value).toHaveText('')
  await page.evaluate(() => window.arrival.update('empty', {}, true))
  await page.clock.runFor(400)
  await expect(word).toHaveText('no data')
  await expect(value).toHaveText('')
})

test('an alert or an armed space keeps the headline', async ({ page }) => {
  await open(page, 1920, 1080)
  const words = await page.evaluate(async () => {
    const { judgeMoment } = await import('/src/hud/judge-moment.ts')
    const state = window.arrival.peek('object')
    const alert = { ...state, alert: { state: 'check_on', zone: 1, still_s: 12, limit_s: 10 } }
    return [judgeMoment(state, false)[0], judgeMoment(alert, false)[0], judgeMoment({ ...state, armed: true }, false)[0]]
  })
  expect(words).toEqual(['Dead zone found', 'An object, not a person', 'An object, not a person'])
})
