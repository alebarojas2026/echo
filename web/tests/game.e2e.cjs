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
  await page.screenshot({ path: path.join(shots, name + '.png') })
}

for (const [mock, label, title] of [
  ['calm', 'ALL GOOD', 'Someone is in the Chair zone.'],
  ['counting', 'ALL GOOD', 'Someone is in the Bathroom zone.'],
  ['alert', 'NO-MOVEMENT ALERT', 'No movement in the Bathroom for 10 s.'],
  ['checkin', 'ALL GOOD', 'Someone is in the Bathroom zone.'],
  ['blind', 'SENSOR BLIND', 'The radio cannot read the room right now.'],
]) {
  test(`phone ${mock} at 390x844`, async ({ page }) => {
    const errors = await open(page, `/src/game/phone/index.html?mock=${mock}`, 390, 844)
    await expect(page.getByTestId('phone-label')).toHaveText(label)
    await expect(page.getByTestId('phone-title')).toHaveText(title)
    if (mock === 'checkin') await expect(page.getByTestId('phone-checkin')).toContainText('Last check-in')
    expect(await smallText(page, '#label, #title, #detail, #checkin, #sound')).toEqual([])
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
  await page.getByRole('button', { name: /Chair/ }).click()
  await expect(page.locator('#result')).toContainText('No data from the board')
  await expect(page.locator('#found')).toHaveText('__')
  await shot(page, 'game-nodata')
})
