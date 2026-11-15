// The crowd game (/game/) and the caregiver phone page (/phone/), driven by their ?mock= states.
// Run: npx playwright test --config game.config.cjs. Set HUD_SCREENSHOTS=<folder> to keep a picture of each.
const { test, expect } = require('@playwright/test')
const fs = require('node:fs')
const path = require('node:path')
const shots = process.env.HUD_SCREENSHOTS

// Every bit of text on the page that someone reads must be 28 px or more (AGENTS.md Style).
async function smallText(page, selector) {
  return page.$$eval(selector, (els) => els
    .filter((el) => el.textContent.trim() && el.getClientRects().length)
    .map((el) => [el.textContent.trim().slice(0, 30), parseFloat(getComputedStyle(el).fontSize)])
    .filter(([, px]) => px < 28))
}

async function open(page, url, width, height) {
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.setViewportSize({ width, height })
  await page.goto(url)
  await page.evaluate(() => document.fonts.ready)
  return errors
}

async function shot(page, name) {
  if (!shots) return
  fs.mkdirSync(shots, { recursive: true })
  await page.waitForTimeout(300) // let a text fade finish
  await page.screenshot({ path: path.join(shots, name + '.png') })
}

for (const [mock, label, title] of [
  ['calm', 'ALL GOOD', 'Someone is in the Chair zone.'],
  ['counting', 'ALL GOOD', 'Someone is in the Bathroom zone.'],
  ['alert', 'NO-MOVEMENT ALERT', 'No movement in the Bathroom for 10 s.'],
  ['checkin', 'ALL GOOD', 'Someone is in the Bathroom zone.'],
  ['blind', 'SENSOR BLIND', 'The radio cannot read the room right now.'],
  ['armed', 'ARMED', 'Armed.'],
  ['intrusion', 'INTRUSION', 'Someone is in the Bathroom zone.'],
  ['passed', 'ARMED', 'Armed.'],
  ['tamper', 'SENSOR BLIND', 'The radio cannot read the room right now.'],
]) {
  test(`phone ${mock} at 390x844`, async ({ page }) => {
    const errors = await open(page, `/src/game/phone/index.html?mock=${mock}`, 390, 844)
    await expect(page.getByTestId('phone-label')).toHaveText(label)
    await expect(page.getByTestId('phone-title')).toHaveText(title)
    if (mock === 'checkin') await expect(page.getByTestId('phone-checkin')).toContainText('Last check-in')
    if (mock === 'passed') await expect(page.getByTestId('phone-passed')).toHaveText(/^Someone passed by/)
    if (mock === 'tamper') await expect(page.getByTestId('phone-tamper')).toHaveText('East beacon unplugged while armed.')
    expect(await smallText(page, '#label, #title, #detail, #passed, #tamper, #checkin, #sound')).toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    expect(errors.filter((e) => !e.includes('vibrate'))).toEqual([])
    await shot(page, 'phone-' + mock)
  })
}

test('phone with no board says NO DATA, never an empty room', async ({ page }) => {
  await open(page, '/src/game/phone/index.html?ws=ws://127.0.0.1:9/ws', 390, 844)
  await expect(page.getByTestId('phone-label')).toHaveText('NO DATA')
  await shot(page, 'phone-nodata')
})

for (const [mock, source, found, hidden] of [
  ['ready', 'LIVE', '__', '__'],
  ['round', 'LIVE', '3', '2'],
  ['result', 'LIVE', '3', '2'],
  ['practice', 'SIM', '__', '__'],
  ['blind', 'SENSOR BLIND', '__', '__'],
]) {
  test(`game ${mock} at 1920x1080`, async ({ page }) => {
    const errors = await open(page, `/src/game/index.html?mock=${mock}`, 1920, 1080)
    await expect(page.getByTestId('game-source')).toHaveText(source)
    await expect(page.locator('#found')).toHaveText(found)
    await expect(page.locator('#hidden')).toHaveText(hidden)
    if (mock === 'result') await expect(page.locator('#result')).toContainText('You hid!')
    expect(await smallText(page, 'h1, h2, p, span, strong, button')).toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight)).toBe(true)
    expect(errors).toEqual([])
    await shot(page, 'game-' + mock)
  })
}

test('game with no board says NO DATA and a tap is not counted', async ({ page }) => {
  await open(page, '/src/game/index.html?ws=ws://127.0.0.1:9/ws', 1920, 1080)
  await expect(page.getByTestId('game-source')).toHaveText('NO DATA')
  // Whichever zones the layout file has: the first one on the floor.
  await page.locator('#floor button').first().click()
  await expect(page.locator('#result')).toContainText('No data from the board')
  await expect(page.locator('#found')).toHaveText('__')
  await shot(page, 'game-nodata')
})

test('both pages follow the zones in /nodes.json (the desk strip)', async ({ page }) => {
  const zones = [{ id: 1, side: 'W', name: 'Living room', still_alert_s: null }, { id: 2, side: 'E', name: 'Bathroom', still_alert_s: 10 }]
  await page.route('**/nodes.json', (route) => route.fulfill({ json: { zones } }))
  await open(page, '/src/game/index.html?mock=result', 1920, 1080)
  await expect(page.locator('#floor button')).toHaveCount(2)
  await expect(page.locator('#floor button').first()).toContainText('Living room')
  await expect(page.locator('#compass')).toHaveText('WestEast')
  await expect(page.locator('#hint')).toHaveText('Tap the zone, or press 1 to 2.')
  await expect(page.locator('#result')).toContainText('Living room')
  expect(await smallText(page, 'h1, h2, p, span, strong, button')).toEqual([])
  await shot(page, 'game-desk')
  await page.goto('/src/game/phone/index.html?mock=alert')
  await expect(page.getByTestId('phone-title')).toHaveText('No movement in the room for 10 s.')   // zone 4 isn't in this layout
})

// The phone against a stand-in brain: states at 10 a second and events on the same socket (CONTRACTS.md section 5).
// The page's chime is counted by a stand-in AudioContext (two tones per chime).
async function brain(page) {
  await page.addInitScript(() => {
    window.tones = 0
    const node = () => ({ connect: (next) => next ?? node(), frequency: {}, gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} }, start() {}, stop() {} })
    window.AudioContext = class { constructor() { this.currentTime = 0; this.destination = {} } resume() { return Promise.resolve() } createOscillator() { window.tones += 1; return node() } createGain() { return node() } }
  })
  const feed = { state: null, socket: null }
  let seq = 0
  await page.routeWebSocket(/:8765\/ws$/, (ws) => {
    feed.socket = ws
    const timer = setInterval(() => feed.state && ws.send(JSON.stringify({ ...feed.state, t: Date.now(), seq: ++seq })), 100)
    ws.onClose(() => clearInterval(timer))
  })
  feed.event = (kind, info = {}) => feed.socket.send(JSON.stringify({ v: 2, type: 'event', t: Date.now(), seq: ++seq, src: 'live', id: `e${seq}`, kind, info }))
  return feed
}
const live = { v: 2, type: 'state', src: 'live', health: { status: 'ok', blind: [], reason: null }, checkin: null, alert: { state: 'none', zone: null, still_s: 0, limit_s: null } }
const someone = { present: true, kind: 'person', zone: 2, zone_set: [2], motion: 'moving' }
const nobody = { present: false, kind: 'none', zone: 0, zone_set: [], motion: null }
const chimes = async (page) => (await page.evaluate(() => window.tones)) / 2

test('phone: a person in pred with no event is never an intrusion (a late join shows Armed.)', async ({ page }) => {
  const feed = await brain(page)
  // Someone has been standing there since before the page opened; the intrusion, if any, was before it connected.
  feed.state = { ...live, armed: true, pred: someone }
  const errors = await open(page, '/src/game/phone/index.html', 390, 844)
  await page.getByRole('button', { name: 'Tap to turn on sound' }).click()
  await expect(page.getByTestId('phone-label')).toHaveText('ARMED')
  await expect(page.getByTestId('phone-title')).toHaveText('Armed.')
  await page.waitForTimeout(1500)
  await expect(page.getByTestId('phone-label')).toHaveText('ARMED')
  expect(await chimes(page)).toBe(1) // only the test chime from the sound button
  expect(errors).toEqual([])
  await shot(page, 'phone-late-join')
})

test('phone: the intrusion event raises the card with one chime; disarmed clears it', async ({ page }) => {
  const feed = await brain(page)
  feed.state = { ...live, armed: true, pred: nobody }
  const errors = await open(page, '/src/game/phone/index.html', 390, 844)
  await page.getByRole('button', { name: 'Tap to turn on sound' }).click()
  await expect(page.getByTestId('phone-title')).toHaveText('Armed.')
  feed.state = { ...live, armed: true, pred: someone }
  feed.event('intrusion', { zone: 2 })
  await expect(page.getByTestId('phone-label')).toHaveText('INTRUSION')
  await expect(page.getByTestId('phone-title')).toHaveText('Someone is in the Right zone.')
  await expect(page.locator('body')).toHaveAttribute('data-mode', 'intrusion')
  feed.state = { ...live, armed: true, pred: nobody } // they left: the intrusion stays until disarmed
  await page.waitForTimeout(800)
  await expect(page.getByTestId('phone-label')).toHaveText('INTRUSION')
  expect(await chimes(page)).toBe(2)
  expect(await smallText(page, '#label, #title, #detail, #passed, #tamper, #checkin, #sound')).toEqual([])
  await shot(page, 'phone-intrusion-event')
  feed.event('disarmed')
  feed.state = { ...live, armed: false, pred: nobody }
  await expect(page.getByTestId('phone-label')).toHaveText('ALL GOOD')
  await expect(page.getByTestId('phone-title')).toHaveText('Nobody is in the room.')
  expect(errors).toEqual([])
  await shot(page, 'phone-disarmed')
})

test('phone: passed_by is one calm line with no alarm and no chime, gone after a few seconds', async ({ page }) => {
  const feed = await brain(page)
  feed.state = { ...live, armed: true, pred: someone }
  const errors = await open(page, '/src/game/phone/index.html', 390, 844)
  await page.getByRole('button', { name: 'Tap to turn on sound' }).click()
  await expect(page.getByTestId('phone-title')).toHaveText('Armed.')
  feed.event('passed_by', { zone: 2 })
  feed.state = { ...live, armed: true, pred: nobody }
  await expect(page.getByTestId('phone-passed')).toHaveText('Someone passed by on the right.')
  await expect(page.getByTestId('phone-label')).toHaveText('ARMED')
  await expect(page.locator('body')).toHaveAttribute('data-mode', 'armed')
  expect(await chimes(page)).toBe(1)
  expect(await smallText(page, '#label, #title, #detail, #passed, #tamper, #checkin, #sound')).toEqual([])
  await shot(page, 'phone-passed-by')
  await expect(page.getByTestId('phone-passed')).toBeHidden({ timeout: 7000 })
  expect(errors).toEqual([])
})

test('phone: a device unplugged while armed is named from /nodes.json', async ({ page }) => {
  const feed = await brain(page)
  feed.state = { ...live, armed: true, pred: null, health: { status: 'blind', blind: ['east>unoq:ble'], reason: 'rate' }, tamper: ['east'] }
  const errors = await open(page, '/src/game/phone/index.html', 390, 844)
  await expect(page.getByTestId('phone-tamper')).toHaveText('East beacon unplugged while armed.')
  await expect(page.getByTestId('phone-label')).toHaveText('SENSOR BLIND')
  feed.state = { ...feed.state, tamper: [] }
  await expect(page.getByTestId('phone-tamper')).toBeHidden()
  expect(errors).toEqual([])
})
