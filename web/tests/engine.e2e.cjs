const { test, expect } = require('@playwright/test')
const fs = require('node:fs'), path = require('node:path')
const shots = process.env.HUD_SCREENSHOTS
// The kit as it is: three devices (radio/layouts/gate.json), whatever radio/nodes.json holds today.
const gate = require('../../radio/layouts/gate.json')

// The engine room (/engine/, a second screen) with its simulated kit: every scene at both sizes.
async function open(page, scene, width, height) {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.setViewportSize({ width, height })
  await page.route('**/nodes.json', route => route.fulfill({ json: gate }))
  await page.goto('/src/engine/index.html?mock=' + scene)
  await expect(page.getByTestId('engine-source')).toHaveText(scene === 'none' ? 'No board' : 'Simulated')
  return errors
}
// Nothing under 20 px, and the whole screen on one page.
async function readable(page) {
  expect(await page.evaluate(() => [...document.querySelectorAll('#engine *')].filter(e => e.children.length === 0 && e.textContent.trim() && parseFloat(getComputedStyle(e).fontSize) < 20).map(e => e.textContent))).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight && document.documentElement.scrollWidth <= innerWidth)).toBe(true)
}
async function shot(page, name) {
  if (shots) { fs.mkdirSync(shots, { recursive: true }); await page.screenshot({ path: path.join(shots, name + '.png') }) }
}

for (const [width, height] of [[1920, 1080], [1440, 900]]) {
  test(`running: three devices, the head counting up, both witnesses signing at ${width}`, async ({ page }) => {
    const errors = await open(page, 'running', width, height)
    await expect(page.getByTestId('engine-witnesses')).toHaveText('2 of 2')
    await expect(page.locator('.eng-device')).toHaveCount(3)
    await expect(page.locator('.eng-device h2')).toHaveText(['Board', 'Pi A', 'Pi B'])
    await expect(page).toHaveTitle('Echo: engine room')
    await expect(page.locator('.eng-top h1')).toHaveText('EchoEngine room')
    const head = () => page.getByTestId('engine-head').textContent()
    const first = await head()
    await expect.poll(head, { timeout: 8000 }).not.toBe(first) // the record grows while we watch
    await expect(page.locator('[data-testid="engine-strip"] .eng-block').last()).toContainText(await head())
    await expect(page.getByTestId('engine-verified')).toContainText('ago', { timeout: 8000 })
    await expect(page.getByTestId('engine-watch')).toContainText('nothing measured')
    await readable(page)
    await shot(page, `engine-${width}-running`)
    expect(errors).toEqual([])
  })

  test(`a silent witness is said in words and the chain goes on at ${width}`, async ({ page }) => {
    const errors = await open(page, 'silent', width, height)
    await expect(page.getByTestId('engine-witnesses')).toHaveText('1 of 2', { timeout: 30000 })
    const quiet = page.locator('.eng-device[data-state="quiet"]')
    await expect(quiet).toHaveCount(1)
    await expect(quiet).toContainText('Silent witness')
    await expect(quiet).toContainText('The chain goes on')
    // The fault colour is on the words that name the fault; the devices that are fine carry none of it.
    await expect(quiet.locator('.eng-signed')).toHaveClass(/eng-fault/)
    await expect(page.locator('.eng-device[data-state="ok"] .eng-fault')).toHaveCount(0)
    const head = await page.getByTestId('engine-head').textContent()
    await expect.poll(() => page.getByTestId('engine-head').textContent(), { timeout: 8000 }).not.toBe(head)
    await readable(page)
    await shot(page, `engine-${width}-silent`)
    expect(errors).toEqual([])
  })

  test(`prove it shows the board's own result, a broken chain names its record, and no board says so at ${width}`, async ({ page }) => {
    let errors = await open(page, 'running', width, height)
    await expect(page.getByTestId('engine-prove-result')).toHaveText('')
    await page.getByTestId('engine-prove').click()
    await expect(page.getByTestId('engine-prove-result')).toContainText('was altered in a copy: the chain breaks here. The real record is untouched.')
    await expect(page.locator('.eng-strip--copy .eng-block--altered')).toHaveCount(1)
    await expect(page.locator('[data-testid="engine-strip"] .eng-block--altered')).toHaveCount(0) // never the real strip
    await readable(page)
    await shot(page, `engine-${width}-prove`)
    expect(errors).toEqual([])

    errors = await open(page, 'broken', width, height)
    await expect(page.getByTestId('engine-verified')).toHaveText('No')
    await expect(page.locator('.eng-head.eng-fault')).toContainText('the chain breaks at record #')
    await expect(page.locator('[data-testid="engine-strip"] .eng-block--bad')).not.toHaveCount(0)
    await shot(page, `engine-${width}-broken`)
    expect(errors).toEqual([])

    errors = await open(page, 'answer', width, height)
    await expect(page.getByTestId('engine-ask')).toContainText(/Cites \d+ records, #[\d,]+ to #[\d,]+/, { timeout: 10000 })
    await expect(page.getByTestId('engine-ask')).toContainText('the chain verified over them')
    // A story of several sentences with the detective's five steps: the steps and the cited records are all on
    // the page, inside the panel, and the page does not scroll.
    await expect(page.locator('.eng-steps li')).toHaveCount(5)
    const fit = await page.evaluate(() => {
      const box = document.querySelector('[data-testid="engine-ask"]')
      const inner = box.getBoundingClientRect().bottom - parseFloat(getComputedStyle(box).paddingBottom)
      return { scrolls: document.documentElement.scrollHeight > window.innerHeight, lowest: Math.max(...[...box.children].map((e) => e.getBoundingClientRect().bottom)), inner }
    })
    expect(fit.scrolls).toBe(false)
    expect(fit.lowest).toBeLessThanOrEqual(fit.inner + 1)
    await expect(page.locator('[data-testid="engine-strip"] .eng-block--cited')).not.toHaveCount(0)
    await shot(page, `engine-${width}-answer`)
    expect(errors).toEqual([])

    errors = await open(page, 'none', width, height)
    await expect(page.getByTestId('engine-head')).toHaveText('__')
    await page.getByTestId('engine-prove').click()
    await expect(page.getByTestId('engine-prove-result')).toHaveText('The board did not answer, so nothing was checked.')
    await readable(page)
    await shot(page, `engine-${width}-none`)
    expect(errors).toEqual([])
  })
}
