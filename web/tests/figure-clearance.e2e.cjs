const { test, expect } = require('@playwright/test')
for (const fallback of [false, true]) for (const [width, height] of [[1920, 1080], [1440, 900]]) {
  test(`figure masks strokes and labels at ${width}, fallback ${fallback}`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    if (fallback) await page.route('**/assets/person.glb*', route => route.request().resourceType() === 'fetch' ? route.abort() : route.continue())
    await page.goto('/tests/figure-clearance.html')
    await expect.poll(() => page.evaluate(() => window.fixture?.ready)).toBe(fallback ? 'capsule' : 'loaded')
    await expect(page.getByText('Pi A', { exact: true })).toBeHidden()
    await expect(page.getByText('Board', { exact: true })).toBeVisible()
    const result = await page.evaluate(async () => {
      const { figure, stroke, pixels, view } = window.fixture
      stroke.visible = false; figure.object.visible = false
      const empty = await pixels()
      stroke.visible = true
      const lineOnly = await pixels()
      stroke.visible = false; figure.object.visible = true
      const body = await pixels()
      stroke.visible = true
      const crossing = await pixels()
      const width = view.renderer.domElement.width
      const isBody = i => body[i] !== empty[i] || body[i + 1] !== empty[i + 1] || body[i + 2] !== empty[i + 2]
      let inside = 0, changed = 0, crossed = 0
      for (let i = width * 4; i < body.length - width * 4; i += 4) {
        if (![i, i - 4, i + 4, i - width * 4, i + width * 4].every(isBody)) continue
        inside++
        if (lineOnly[i] !== empty[i] || lineOnly[i + 1] !== empty[i + 1] || lineOnly[i + 2] !== empty[i + 2]) crossed++
        if (crossing[i] !== body[i] || crossing[i + 1] !== body[i + 1] || crossing[i + 2] !== body[i + 2]) changed++
      }
      return { inside, changed, crossed }
    })
    expect(result.inside).toBeGreaterThan(1000)
    expect(result.crossed).toBeGreaterThan(100)
    expect(result.changed).toBe(0)
    await page.evaluate(() => { const f = window.fixture; f.figure.object.position.x = 0.8; f.view.requestRender() })
    await expect(page.getByText('Pi A', { exact: true })).toBeVisible()
    await page.evaluate(() => {
      const f = window.fixture
      f.figure.setMoving(true); f.figure.setHeading(0.6); f.figure.update(300)
      f.view.moveLabel(f.crossing, new f.Vector3(0.8, 0.6, 0))
    })
    await expect(page.getByText('Pi A', { exact: true })).toBeHidden()
    await page.setViewportSize({ width: 1100, height: 800 })
    await expect(page.getByText('Pi A', { exact: true })).toBeHidden()
    await page.evaluate(() => { window.fixture.figure.object.visible = false; window.fixture.view.requestRender() })
    await expect(page.getByText('Pi A', { exact: true })).toBeVisible()
  })
}
const fs = require('node:fs')
const path = require('node:path')
for (const [width, height] of [[1920, 1080], [1440, 900]]) for (const scene of ['still', 'alert', 'object', 'blind', 'empty']) {
  test(`${scene} screen stays clean at ${width}`, async ({ page }) => {
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.setViewportSize({ width, height })
    await page.clock.install()
    await page.goto('/?mock=' + (scene === 'alert' ? 'still' : scene))
    await expect(page.locator('#room')).toHaveAttribute('data-figure', 'loaded')
    await page.clock.runFor(scene === 'alert' ? 11000 : scene === 'still' ? 7200 : 1000)
    await page.evaluate(() => document.fonts.ready)
    if (process.env.HUD_SCREENSHOTS) {
      fs.mkdirSync(process.env.HUD_SCREENSHOTS, { recursive: true })
      await page.screenshot({ path: path.join(process.env.HUD_SCREENSHOTS, `${width}x${height}${scene === 'still' ? '' : '-' + scene}.png`) })
    }
    expect(errors).toEqual([])
  })
}
