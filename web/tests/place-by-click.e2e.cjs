const { test, expect } = require('@playwright/test')
const fs = require('node:fs'), path = require('node:path')
const gate = require('../../radio/layouts/gate.json')
const shots = process.env.HUD_SCREENSHOTS

// Placing the kit by clicking a desk (web/src/room/place.ts), on the hall model the repo carries. Nothing is
// written anywhere: the save endpoints are answered here, and the page load after a save is served what was saved,
// as the dev server and the board do.
async function setup(page) {
  const saved = { fits: [], nodes: [] }, errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.route('**/nodes.json', (route) => {
    const places = saved.nodes.at(-1) ?? []
    return route.fulfill({ json: { ...gate, nodes: gate.nodes.map((n) => ({ ...n, xyz_m: places.find((p) => p.id === n.id)?.xyz_m ?? n.xyz_m })) } })
  })
  await page.route('**/__room-scan', async (route) => {
    if (route.request().method() === 'POST') {
      saved.fits.push(route.request().postDataJSON())
      return route.fulfill({ json: { saved: 'test' } })
    }
    const res = await route.fetch()
    const body = await res.json()
    return route.fulfill({ json: saved.fits.length ? { ...body, fit: saved.fits.at(-1) } : body })
  })
  await page.route('**/__nodes', (route) => {
    saved.nodes.push(route.request().postDataJSON())
    return route.fulfill({ json: { saved: 'test' } })
  })
  return { saved, errors }
}
const ASK = 'Click the desk the board and Pi A are on.'
const room = (page) => page.locator('#room')
const placing = async (page) => JSON.parse((await room(page).getAttribute('data-placing')) ?? 'null')
const shot = async (page, name) => {
  if (!shots) return
  fs.mkdirSync(shots, { recursive: true })
  await page.screenshot({ path: path.join(shots, `${name}.png`) })
}

/** Presses on points over the far-left block until a desk there, with a row on both sides, is taken. */
async function takeFarDesk(page, press) {
  const { width, height } = page.viewportSize()
  for (const fy of [0.52, 0.56, 0.6, 0.48, 0.64]) for (const fx of [0.22, 0.25, 0.28, 0.2, 0.31]) {
    await press(width * fx, height * fy)
    const at = await placing(page)
    if (at && at.block === 1 && at.row >= 3 && at.row <= 8) return at
  }
  throw new Error('no desk of the far-left block under any of the points tried')
}

for (const [width, height] of [[1920, 1080], [1440, 900]]) {
  test(`click a desk in a far block, Enter, and the page stands there after it loads again at ${width}`, async ({ page }) => {
    const { saved, errors } = await setup(page)
    await page.setViewportSize({ width, height })
    await page.goto('/?mock=step_in&op=1')
    await expect(room(page)).toHaveAttribute('data-scan', 'loaded', { timeout: 30000 })
    const before = await room(page).getAttribute('data-scan-at')
    // The way in: the operator's control, or P.
    await expect(page.getByTestId('place-open')).toBeVisible()
    await page.getByTestId('place-open').click()
    const panel = page.getByTestId('place')
    // The first instruction names the devices on the desk to click; the line under it says where Pi B is taken to be.
    await expect(panel.locator('.room-place-say')).toHaveText(ASK)
    await expect(panel.locator('.room-place-help')).toHaveText('Pi B is on the row behind it. Press G if Pi B is on the row in front.')
    await expect(page.locator('html')).toHaveAttribute('data-room-placing', '1')
    await expect(page.locator('#hud')).toBeHidden() // the hall has the whole screen
    await expect(panel.locator('[data-do="save"]')).toBeDisabled()
    // The operator drawer is closed (its keys R M H T B act only while it is open), and no other key reaches the
    // page: O does not open the drawer again, / does not open the question box, nothing is saved or sent.
    await expect(page.locator('html')).toHaveAttribute('data-hud-operator', 'closed')
    for (const key of ['b', 'r', 't', 'm', 'h', 'o', '/', 'ArrowLeft', 'Enter']) await page.keyboard.press(key)
    await expect(page.locator('html')).toHaveAttribute('data-hud-operator', 'closed')
    await expect(page.locator('dialog[open]')).toHaveCount(0)
    await expect(panel.locator('.room-place-say')).toHaveText(ASK)
    expect(saved.fits).toHaveLength(0)
    await page.waitForTimeout(300)
    await shot(page, `place-${width}-1-ask`)

    const at = await takeFarDesk(page, (x, y) => page.mouse.click(x, y))
    await expect(panel).toContainText('Board and Pi A on this desk, Pi B on the row behind. Press Enter to save, or click another desk.')
    expect(at.side).toBe('behind')
    expect(await room(page).getAttribute('data-scan-at')).not.toBe(before) // the kit is drawn there at once
    await expect(page.locator('.room-place-tag:not([hidden])')).toHaveText(['Board and Pi A', 'Pi B'])
    await expect(panel.locator('.room-place-help')).toHaveText('Press G if Pi B is on the row in front.')
    await shot(page, `place-${width}-2-desk-clicked`)

    // The other side, and back.
    await page.keyboard.press('g')
    await expect(panel).toContainText('Pi B on the row in front.')
    await expect(panel.locator('.room-place-help')).toHaveText('Press G if Pi B is on the row behind.')
    expect((await placing(page)).side).toBe('front')
    await shot(page, `place-${width}-3-other-side`)
    await panel.locator('[data-do="flip"]').click()
    await expect(panel).toContainText('Pi B on the row behind.')
    expect(saved.fits).toHaveLength(0) // nothing is saved until Enter

    await page.keyboard.press('Enter')
    const words = `Saved: Row ${at.row}, block 1. Board and Pi A on that desk, Pi B on the row behind.`
    // The page loads again and says what was saved; the hall stands where it was put and the camera comes down.
    await expect(page.getByTestId('place-saved')).toHaveText(words, { timeout: 30000 })
    expect(saved.fits).toHaveLength(1)
    expect(saved.nodes.at(-1).map((n) => n.id).sort()).toEqual(['pi5', 'pi5b', 'unoq'])
    const fit = saved.fits[0]
    await expect(room(page)).toHaveAttribute('data-scan-at', [...fit.offset_m, fit.yaw_deg].join(','), { timeout: 30000 })
    await expect(page.locator('html')).not.toHaveAttribute('data-room-placing', '1')
    await expect(page.locator('.hud-operator')).toBeHidden() // it would lie over the place just saved
    // The note lies on none of the words at the top of the page: the "Simulated data" strip, the name and the claim.
    const covered = await page.evaluate(() => {
      const note = document.querySelector('[data-testid="place-saved"]').getBoundingClientRect()
      const seen = (e) => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden'
      const words = [...document.querySelectorAll('.room-sim, .judge > header > *, .hud-arrival > header > *, .sealed-record')].filter(seen)
      return words
        .filter((e) => {
          const r = e.getBoundingClientRect()
          return r.bottom > note.top && r.top < note.bottom && r.right > note.left && r.left < note.right
        })
        .map((e) => (e.textContent ?? '').trim().slice(0, 40))
    })
    if ((await page.locator('html').getAttribute('data-judge-layout')) === 'hall') expect(covered).toEqual([])
    await shot(page, `place-${width}-4-saved`)
    await expect(room(page)).toHaveAttribute('data-view', 'square', { timeout: 20000 })
    await page.waitForTimeout(400)
    await shot(page, `place-${width}-5-landed`)

    // Esc leaves with nothing saved and the hall back where it was.
    const kept = await room(page).getAttribute('data-scan-at')
    await page.keyboard.press('p')
    await expect(panel).toBeVisible()
    await page.mouse.click(width * 0.7, height * 0.45)
    await page.mouse.click(width * 0.72, height * 0.5)
    await page.keyboard.press('Escape')
    await expect(panel).toHaveCount(0)
    await expect(page.locator('html')).not.toHaveAttribute('data-room-placing', '1')
    expect(await room(page).getAttribute('data-scan-at')).toBe(kept)
    expect(saved.fits).toHaveLength(1)
    await expect(page.locator('#hud')).toBeVisible()
    // The operator drawer stepped aside while the saved place was shown, and is back once the words have gone.
    await expect(page.getByTestId('place-saved')).toHaveCount(0, { timeout: 15000 })
    await expect(page.locator('html')).not.toHaveAttribute('data-room-placed', '1')
    expect(errors).toEqual([])
  })
}

test.describe('with a finger', () => {
  test.use({ hasTouch: true })
  test('a tap takes a desk and the Save control saves it', async ({ page }) => {
    const { saved, errors } = await setup(page)
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/?mock=step_in&place=1') // no keys on a phone: the address opens it
    const panel = page.getByTestId('place')
    await expect(panel).toContainText(ASK, { timeout: 30000 })
    await page.waitForTimeout(300)
    const at = await takeFarDesk(page, (x, y) => page.touchscreen.tap(x, y))
    await expect(panel).toContainText('Press Enter to save, or click another desk.')
    await panel.locator('[data-do="save"]').tap()
    await expect(page.getByTestId('place-saved')).toContainText(`Saved: Row ${at.row}, block 1.`, { timeout: 30000 })
    expect(saved.fits).toHaveLength(1)
    await expect(page).not.toHaveURL(/place=1/) // the page that loads again is the plain one
    expect(errors).toEqual([])
  })
})
