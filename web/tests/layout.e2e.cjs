const layoutFixture = require('./layout-fixture.cjs')
const { test, expect } = require('@playwright/test')
for (const [width, height] of [[1920, 1080], [1280, 720]]) {
  for (const scene of ['still', 'object', 'blind', 'empty']) {
    test(`${scene} fits the rail at ${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height })
      await page.clock.install()
      await page.goto('/?mock=' + scene)
      await page.clock.runFor(7200)
      const bounds = await page.locator('#hud').evaluate(root => {
        const rail = root.getBoundingClientRect()
        return {
          scroll: root.scrollHeight > root.clientHeight,
          outside: [...root.querySelectorAll('*')].filter(el => {
            const rect = el.getBoundingClientRect()
            return rect.width && rect.height && (rect.left < rail.left - 1 || rect.right > rail.right + 1)
          }).map(el => el.getAttribute('data-testid') || el.tagName),
        }
      })
      expect(bounds).toEqual({ scroll: false, outside: [] })
    })
  }
}
