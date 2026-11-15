const { test, expect } = require('@playwright/test')
const path = require('node:path')
require('./layout-fixture.cjs')
const shots = process.env.HUD_SCREENSHOTS
const PERSON = 'rgb(255, 159, 67)'

async function open(page, width = 1920, height = 1080) {
  await page.setViewportSize({ width, height })
  await page.clock.install({ time: new Date('2026-01-01T00:00:00Z') })
  await page.clock.pauseAt(new Date('2026-01-01T00:00:01Z'))
  await page.goto('/tests/arrival-harness.html')
  await expect.poll(() => page.evaluate(() => !!window.arrival)).toBe(true)
  await page.clock.runFor(200)
}

// Plays readings at the board's rate, 10 a second. frame(i) gives the drop on the first side's links (first) and
// on the others, whether a person is on the first side, and whether its links are stale or have no baseline.
async function play(page, count, frame) {
  await page.evaluate(([count, source]) => {
    const frame = new Function('return (' + source + ')')()
    const first = document.querySelector('[data-testid="signal-strip"] [data-testid="signal-row"]')
    const mine = new Set((first?.dataset.links ?? '').split(','))
    const zone = Number(first?.dataset.zone ?? 0)
    window.signalSeq ??= 0
    window.signalFrames = Array.from({ length: count }, (_, i) => () => {
      const f = frame(i)
      const base = window.arrival.peek('empty')
      const links = f.links === 'none' ? [] : base.links.map(link => {
        if (f.links === 'no-baseline') return { ...link, base_dbm: null, drop_db: null, expected_hz: null }
        const drop = mine.has(link.id) ? f.first : f.others ?? 0.2
        const stale = !!f.stale && mine.has(link.id)
        return { ...link, drop_db: drop, dbm: link.base_dbm - drop, status: stale ? 'stale' : 'ok', rate_hz: stale ? 0 : 9.4 }
      })
      const pred = f.present ? { present: true, kind: 'person', zone, zone_set: [zone], probs: [], motion: 'still', still_s: 0, why: [] } : base.pred
      window.arrival.update('empty', { links, pred, seq: ++window.signalSeq, t: Date.now() })
    })
  }, [count, frame.toString()])
  for (let i = 0; i < count; i++) {
    await page.evaluate(i => window.signalFrames[i](), i)
    await page.clock.runFor(100)
  }
}
const capture = async (page, name) => { if (shots) await page.screenshot({ path: path.join(shots, name + '.png') }) }
// How many different heights the first side's line is drawn at: a few for a flat line and its end dot, many for a dip or a wiggle.
const heights = (page, view) => page.evaluate(view => {
  const canvas = document.querySelector('[data-testid="' + view + '"] canvas')
  const { data, width, height } = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height)
  const tops = new Set()
  for (let x = 0; x < width; x++) {
    for (let y = 0; y < height; y++) {
      const i = 4 * (y * width + x)
      if (data[i + 3] > 200 && data[i] > 100) { tops.add(y); break }
    }
  }
  return tops.size
}, view)

for (const [width, height] of [[1920, 1080], [1440, 900]]) {
  test(`empty, a step-in dip and a wave at ${width}`, async ({ page }) => {
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await open(page, width, height)
    const band = page.getByTestId('signal-arrival')
    const strip = page.getByTestId('signal-strip')
    const rows = band.getByTestId('signal-row')
    await play(page, 60, () => ({ first: 0.2 }))
    await expect(page.getByTestId('arrival-title')).toHaveText('Nobody is here.')
    await expect(band).toBeVisible()
    expect(await rows.count()).toBeGreaterThanOrEqual(2)
    await expect(rows.first().getByTestId('signal-value')).toHaveText('−0.2 dB')
    await expect(rows.first()).toHaveAttribute('data-present', 'false')
    await expect(rows.first()).toHaveAttribute('data-runs', '1')
    expect(await heights(page, 'signal-arrival')).toBeLessThanOrEqual(6)
    for (const text of await band.locator('header span, .signal-name, .signal-value').all()) expect(parseFloat(await text.evaluate(el => getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(28)
    await capture(page, `${width}-empty`)

    // Someone steps in on the first side: its line dips and takes the person colour; the other side stays grey.
    await play(page, 22, i => ({ first: 0.2 + 6.8 * Math.min(1, i / 8), present: i >= 6 }))
    await expect(page.getByTestId('arrival-title')).toHaveText('Found you.')
    await expect(rows.first().getByTestId('signal-value')).toHaveText('−7.0 dB')
    await expect(rows.first()).toHaveAttribute('data-present', 'true')
    await expect(rows.first().locator('.signal-name')).toHaveCSS('color', PERSON)
    await expect(rows.nth(1)).toHaveAttribute('data-present', 'false')
    await expect(rows.nth(1).locator('.signal-name')).not.toHaveCSS('color', PERSON)
    expect(await heights(page, 'signal-arrival')).toBeGreaterThan(12)
    await capture(page, `${width}-step-in`)

    // After the greeting the same trace stays on the main screen as a compact strip.
    await play(page, 40, () => ({ first: 7, present: true }))
    await expect(page.locator('.hud-arrival')).toBeHidden()
    await expect(strip).toBeVisible()
    const box = await strip.boundingBox()
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(640)
    expect(box.y + box.height).toBeLessThanOrEqual(height)

    // A wave: the readings go up and down, and so does the line.
    await play(page, 30, i => ({ first: 5 + 2 * Math.sin(i * 1.3), present: true }))
    expect(await heights(page, 'signal-strip')).toBeGreaterThan(8)
    await expect(strip.getByTestId('signal-row').first()).toHaveAttribute('data-runs', '1')
    await capture(page, `${width}-wave`)
    expect(errors).toEqual([])
  })
}

test('a stale link is a gap, never a flat line', async ({ page }) => {
  await open(page)
  const rows = page.getByTestId('signal-arrival').getByTestId('signal-row')
  const row = rows.first()
  await play(page, 30, () => ({ first: 0.4 }))
  await play(page, 15, () => ({ first: 0, stale: true }))
  await expect(row).toHaveAttribute('data-signal', 'none')
  await expect(row.getByTestId('signal-value')).toHaveText('no signal')
  await play(page, 25, () => ({ first: 0.4 }))
  await expect(row).toHaveAttribute('data-runs', '2')
  await expect(row.getByTestId('signal-value')).toHaveText('−0.4 dB')
  await expect(rows.nth(1)).toHaveAttribute('data-runs', '1')
  await capture(page, '1920-stale-gap')
  // The feed itself stopping is said in words too, and the line stops where the readings did.
  await page.evaluate(() => window.arrival.update('empty', {}, true))
  await page.clock.runFor(300)
  await expect(row.getByTestId('signal-value')).toHaveText('no data')
})

test('before a baseline there is no trace, and a line says why', async ({ page }) => {
  await open(page)
  const band = page.getByTestId('signal-arrival')
  await play(page, 5, () => ({ links: 'no-baseline' }))
  await expect(band.getByTestId('signal-note')).toHaveText('No baseline yet. The trace starts once the empty space is measured.')
  await expect(band.locator('.signal-rows')).toBeHidden()
  await capture(page, '1920-no-baseline')
  await play(page, 5, () => ({ links: 'none' }))
  await expect(band.getByTestId('signal-note')).toHaveText('No radio readings yet.')
  await play(page, 5, () => ({ first: 0.3 }))
  await expect(band.getByTestId('signal-note')).toBeHidden()
  await expect(band.getByTestId('signal-row').first().getByTestId('signal-value')).toHaveText('−0.3 dB')
})
