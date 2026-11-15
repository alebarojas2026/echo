const { test, expect } = require('@playwright/test')
const fs = require('node:fs'), path = require('node:path')
const shots = process.env.HUD_SCREENSHOTS
// The kit as it is: three devices (radio/layouts/gate.json), whatever radio/nodes.json holds today.
const gate = require('../../radio/layouts/gate.json')
const desk = require('../../radio/layouts/desk.json')

// The engine room (/engine/, a second screen) with its simulated kit: every scene at both sizes. One picture:
// the newest record's number, the board's row of records, a row per witness, one button.
async function open(page, scene, width, height, layout = gate) {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.setViewportSize({ width, height })
  await page.route('**/nodes.json', route => route.fulfill({ json: layout }))
  await page.goto('/src/engine/index.html?mock=' + scene)
  await expect(page.getByTestId('engine-source')).toHaveText(scene === 'none' ? 'No board' : 'Simulated')
  return errors
}
// Everything a judge reads is 28 px on a 1920 screen (the picture scales with the screen), and the whole
// screen is on one page: nothing scrolls and nothing hangs over an edge.
async function readable(page) {
  expect(await page.evaluate(() => [...document.querySelectorAll('#engine *')].filter(e => !e.closest('.eng-op') && e.children.length === 0 && e.textContent.trim() && e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden' && parseFloat(getComputedStyle(e).fontSize) < 28 * innerWidth / 1920 - 0.01).map(e => e.textContent))).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight && document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  expect(await page.evaluate(() => [...document.querySelectorAll('#engine *')].filter(e => { const r = e.getBoundingClientRect(); return r.width && getComputedStyle(e).visibility !== 'hidden' && !e.closest('.eng-row') && (r.bottom > innerHeight + 1 || r.right > innerWidth + 1 || r.left < -1 || r.top < -1) }).map(e => e.className))).toEqual([])
}
const names = page => page.locator('[data-testid="engine-record"] > .eng-name')
const realRow = page => page.locator('.eng-track[data-node] .eng-row--chain')
const top = (page, id) => page.getByTestId(id).evaluate(e => e.getBoundingClientRect().top)
async function shot(page, name) {
  if (shots) { fs.mkdirSync(shots, { recursive: true }); await page.screenshot({ path: path.join(shots, name + '.png') }) }
}

for (const [width, height] of [[1920, 1080], [1440, 900]]) {
  test(`running: the number counting up, the board's row, both Pi rows signing at ${width}`, async ({ page }) => {
    const errors = await open(page, 'running', width, height)
    await expect(names(page)).toHaveText(['Board', 'Pi A', 'Pi B'])
    await expect(page).toHaveTitle('Echo: engine room')
    await expect(page.locator('.eng-top h1')).toHaveText('EchoEngine room')
    await expect(page.getByTestId('engine-title')).toHaveText('The sealed record')
    await expect(page.getByTestId('engine-signed')).toHaveText(/^Both signed (now|\d+ s ago)$/)
    const head = () => page.getByTestId('engine-head').textContent()
    await expect(page.getByTestId('engine-head')).toHaveText(/^\d{1,3}(,\d{3})*$/)
    // One row of plain blocks, the newest solid at the right, with nothing written on any of them.
    await expect(realRow(page).locator('.eng-block')).toHaveCount(19)
    await expect(realRow(page).locator('.eng-block').last()).toHaveClass(/eng-block--head/)
    expect((await realRow(page).textContent()).trim()).toBe('')
    // A mark under each record a Pi signed, in each Pi's own row.
    for (const node of ['pi5', 'pi5b']) await expect(page.locator(`.eng-track[data-node="${node}"] .eng-mark i`)).not.toHaveCount(0)
    // The number is the newest block's own label: very large, figures of one width, its edge over the block's.
    const fit = await page.evaluate(() => {
      const n = document.querySelector('[data-testid="engine-head"]'), b = document.querySelector('.eng-block--head'), s = getComputedStyle(n)
      return { size: parseFloat(s.fontSize), tabular: s.fontVariantNumeric, widths: [...new Set([...n.querySelectorAll('.eng-digit')].map(d => Math.round(d.getBoundingClientRect().width * 10)))].length, title: s.fontFamily, weight: s.fontWeight, synthesis: s.fontSynthesisWeight, off: Math.abs(n.getBoundingClientRect().right - b.getBoundingClientRect().right), unit: innerWidth / 1920 }
    })
    expect(fit.size).toBeGreaterThanOrEqual(200 * fit.unit)
    expect(fit.tabular).toContain('tabular-nums')
    expect(fit.widths).toBe(1) // every figure in a box of one width: the title face has no tabular figures
    expect(fit.title).toMatch(/^"?Tenor Sans/)
    expect([fit.weight, fit.synthesis]).toEqual(['400', 'none']) // one weight, and never a faked bold
    expect(fit.off).toBeLessThanOrEqual(1)
    // The record grows while we watch, and the number changing moves nothing.
    const first = await head(), at = [await top(page, 'engine-title'), await top(page, 'engine-record'), await top(page, 'engine-prove')]
    await expect.poll(head, { timeout: 8000 }).not.toBe(first)
    expect([await top(page, 'engine-title'), await top(page, 'engine-record'), await top(page, 'engine-prove')]).toEqual(at)
    await expect(realRow(page).locator('.eng-block').last()).toHaveAttribute('data-seq', (await head()).replace(/,/g, ''))
    await expect(page.getByTestId('engine-verified')).toHaveText(/^Checked (now|\d+ s ago)$/, { timeout: 8000 })
    // The one control: filled in the accent, 88 px tall on a 1920 screen, one sentence beside it.
    const button = await page.getByTestId('engine-prove').evaluate(e => ({ h: e.getBoundingClientRect().height, bg: getComputedStyle(e).backgroundColor, text: e.textContent }))
    const accent = await page.evaluate(() => { const p = document.createElement('p'); p.style.color = 'var(--person)'; document.body.append(p); const c = getComputedStyle(p).color; p.remove(); return c })
    expect(button).toEqual({ h: 88 * width / 1920, bg: accent, text: 'PROVE IT' })
    await expect(page.locator('.eng-prove-note')).toHaveText('Changes one record in a copy and shows where the chain breaks.')
    // The plumbing is the operator's: no readings a second, no meter, no hashes on the judge's picture.
    await expect(page.getByTestId('engine-op')).toBeHidden()
    expect(await page.locator('#engine').innerText()).not.toMatch(/readings a second|privacy meter|camera|microphone/i)
    await readable(page)
    await shot(page, `engine-${width}-running`)
    await page.keyboard.press('o')
    await expect(page.getByTestId('engine-op')).toContainText('readings a second')
    await expect(page.getByTestId('engine-op')).toContainText('nothing measured')
    await page.keyboard.press('o')
    await expect(page.getByTestId('engine-op')).toBeHidden()
    expect(errors).toEqual([])
  })

  test(`a silent witness is said in words and the chain goes on at ${width}`, async ({ page }) => {
    const errors = await open(page, 'silent', width, height)
    const quiet = page.locator('.eng-track[data-state="quiet"]')
    await expect(quiet).toHaveCount(1, { timeout: 30000 })
    await expect(quiet).toHaveAttribute('data-node', 'pi5b')
    await expect(quiet).toContainText(/Silent witness: has not signed for \d+ s\. The chain goes on\./)
    // The fault colour is on the words that name the fault and on that Pi's name; the rows that are fine carry none.
    await expect(quiet.locator('.eng-row-words')).toHaveClass(/eng-fault/)
    await expect(names(page).nth(2)).toHaveClass(/eng-fault/)
    await expect(page.locator('#engine .eng-fault')).toHaveCount(2)
    const colours = await page.evaluate(() => { const p = document.createElement('p'); p.style.color = 'var(--fault)'; document.body.append(p); const c = getComputedStyle(p).color; p.remove(); return [c, getComputedStyle(document.querySelector('.eng-row-words.eng-fault')).color] })
    expect(colours[1]).toBe(colours[0])
    // The one that still signs is the one the line under the rows names.
    await expect(page.getByTestId('engine-signed')).toHaveText(/^Pi A signed (now|\d+ s ago)$/)
    const head = await page.getByTestId('engine-head').textContent()
    await expect.poll(() => page.getByTestId('engine-head').textContent(), { timeout: 8000 }).not.toBe(head)
    await expect(page.getByTestId('engine-title')).toHaveText('The sealed record') // the chain still verifies
    await readable(page)
    await shot(page, `engine-${width}-silent`)
    expect(errors).toEqual([])
  })

  test(`prove it shows the board's own result, a broken chain names its record, and no board says so at ${width}`, async ({ page }) => {
    let errors = await open(page, 'running', width, height)
    await expect(realRow(page).locator('.eng-block')).toHaveCount(19)
    await expect(page.getByTestId('engine-prove-result')).toHaveText('')
    await expect(page.getByTestId('engine-copy')).toBeHidden()
    const at = [await top(page, 'engine-title'), await top(page, 'engine-record'), await top(page, 'engine-prove')]
    await page.getByTestId('engine-prove').click()
    await expect(page.getByTestId('engine-prove-result')).toContainText(/Record #[\d,]+ was altered in a copy: the chain breaks here\. The real record is untouched\./)
    // The copy is drawn under the real row, the altered record and every one after it broken; never the real row.
    await expect(page.getByTestId('engine-copy')).toBeVisible()
    await expect(page.locator('.eng-copy .eng-name')).toHaveText('A copy')
    await expect(page.locator('[data-testid="engine-copy"] .eng-block--altered')).toHaveCount(1)
    await expect(page.locator('[data-testid="engine-copy"] .eng-block--bad')).not.toHaveCount(0)
    await expect(realRow(page).locator('.eng-block--altered, .eng-block--bad')).toHaveCount(0)
    await expect(page.getByTestId('engine-title')).toHaveText('The sealed record')
    await expect(page.getByTestId('engine-verified')).toHaveText(/^Check(ed|ing)/) // the real record still verifies
    expect([await top(page, 'engine-title'), await top(page, 'engine-record'), await top(page, 'engine-prove')]).toEqual(at) // showing it moved nothing
    await readable(page)
    await shot(page, `engine-${width}-prove`)
    expect(errors).toEqual([])

    errors = await open(page, 'broken', width, height)
    await expect(page.getByTestId('engine-title')).toHaveText('The chain does NOT verify')
    await expect(page.getByTestId('engine-title')).toHaveClass(/eng-fault/)
    await expect(page.getByTestId('engine-alarm')).toHaveText(/^It breaks at record #[\d,]+\.$/)
    await expect(page.getByTestId('engine-verified')).toHaveText('Does not verify')
    await expect(page.getByTestId('engine-verified')).toHaveClass(/eng-fault/)
    await expect(realRow(page).locator('.eng-block--bad')).not.toHaveCount(0)
    // Unmissable: the heading itself says it, at heading size.
    expect(await page.getByTestId('engine-title').evaluate(e => parseFloat(getComputedStyle(e).fontSize) / innerWidth * 1920)).toBeGreaterThanOrEqual(56)
    await readable(page)
    await shot(page, `engine-${width}-broken`)
    expect(errors).toEqual([])

    errors = await open(page, 'none', width, height)
    await expect(page.getByTestId('engine-head')).toHaveText('__')
    await expect(page.getByTestId('engine-head')).toBeHidden() // no number is shown that the board did not give
    await expect(page.getByTestId('engine-alarm')).toHaveText('The board is not answering.')
    await page.getByTestId('engine-prove').click()
    await expect(page.getByTestId('engine-prove-result')).toHaveText('The board did not answer, so nothing was checked.')
    await readable(page)
    await shot(page, `engine-${width}-none`)
    expect(errors).toEqual([])
  })

  test(`the last answer keeps its steps and cited records under the picture, with prove it in reach at ${width}`, async ({ page }) => {
    const errors = await open(page, 'answer', width, height)
    await expect(page.getByTestId('engine-ask')).toContainText(/Cites \d+ records, #[\d,]+ to #[\d,]+/, { timeout: 10000 })
    await expect(page.getByTestId('engine-ask')).toContainText('the chain verified over them')
    await expect(page.getByTestId('engine-ask')).toContainText('What happened in the last minute?')
    await expect(page.getByTestId('engine-ask')).toContainText('Nobody was on the spot in the last minute.')
    // A story of several sentences with the detective's five steps: the steps and the cited records are all on
    // the page, inside the answer's own space, above the button, and the page does not scroll.
    await expect(page.locator('.eng-steps li')).toHaveCount(5)
    const fit = await page.evaluate(() => {
      const box = document.querySelector('[data-testid="engine-ask"]')
      return { scrolls: document.documentElement.scrollHeight > window.innerHeight, lowest: Math.max(...[...box.querySelectorAll('p, li')].map((e) => e.getBoundingClientRect().bottom)), inner: box.getBoundingClientRect().bottom, clipped: box.scrollHeight > box.clientHeight + 1, foot: document.querySelector('[data-testid="engine-prove"]').getBoundingClientRect().top }
    })
    expect(fit.scrolls).toBe(false)
    expect(fit.clipped).toBe(false)
    expect(fit.lowest).toBeLessThanOrEqual(fit.inner + 1)
    expect(fit.inner).toBeLessThanOrEqual(fit.foot)
    await expect(realRow(page).locator('.eng-block--cited')).not.toHaveCount(0)
    await expect(page.getByTestId('engine-prove')).toBeInViewport({ ratio: 1 })
    await readable(page)
    await shot(page, `engine-${width}-answer`)
    // Prove it with an answer on the screen: the copy takes the answer's place for a while and nothing moves.
    const at = [await top(page, 'engine-title'), await top(page, 'engine-record'), await top(page, 'engine-prove')]
    await page.getByTestId('engine-prove').click()
    await expect(page.getByTestId('engine-copy')).toBeVisible()
    await expect(page.getByTestId('engine-ask')).toBeHidden()
    expect([await top(page, 'engine-title'), await top(page, 'engine-record'), await top(page, 'engine-prove')]).toEqual(at)
    await readable(page)
    await shot(page, `engine-${width}-answer-prove`)
    expect(errors).toEqual([])
  })

  test(`no witness enrolled, and a signature that does not check, are each said in words at ${width}`, async ({ page }) => {
    let errors = await open(page, 'nowitness', width, height)
    await expect(page.getByTestId('engine-signed')).toHaveText('No witness is enrolled')
    await expect(names(page)).toHaveText(['Board', 'Pi A', 'Pi B'])
    await expect(page.locator('.eng-mark i')).toHaveCount(0)
    await expect(page.locator('#engine .eng-fault')).toHaveCount(0)
    await readable(page)
    await shot(page, `engine-${width}-no-witness`)
    expect(errors).toEqual([])

    errors = await open(page, 'badsig', width, height)
    const bad = page.locator('.eng-track[data-node="pi5b"] .eng-row-words')
    await expect(bad).toHaveText(/^Its signature on record #[\d,]+ did NOT check\.$/)
    await expect(bad).toHaveClass(/eng-fault/)
    await expect(page.getByTestId('engine-signed')).toHaveText(/^Pi A signed/)
    await readable(page)
    await shot(page, `engine-${width}-bad-signature`)
    expect(errors).toEqual([])
  })
}

test('the old five-device desk layout still draws: the board and the two Pis have rows, the beacons none', async ({ page }) => {
  const errors = await open(page, 'running', 1920, 1080, desk)
  await expect(names(page)).toHaveText(['Board', 'Pi A', 'Pi B'])
  await expect(page.getByTestId('engine-signed')).toHaveText(/^Both signed/)
  await expect(realRow(page).locator('.eng-block')).toHaveCount(19)
  await readable(page)
  // The beacons are the operator's: they sign nothing, and their readings are on the operator's lines.
  await page.keyboard.press('o')
  await expect(page.getByTestId('engine-op')).toContainText('East beacon')
  expect(errors).toEqual([])
})
