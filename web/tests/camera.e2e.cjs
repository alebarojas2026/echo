const { test, expect } = require('@playwright/test')
test('camera agreement and the eight-second unplug state', async ({ page }) => {
  await page.clock.install()
  await page.goto('/src/hud/index.html')
  await page.evaluate(async () => {
    const { mountPanel } = await import('/src/hud/judge-camera-panel.ts')
    const { mockState } = await import('/src/room/mock.ts')
    document.body.innerHTML = '<section id="panel"></section>'
    window.panel = mountPanel(document.querySelector('#panel'))
    window.state = mockState('camera', 0, 1000)
    window.state.teacher = { present: true, zone: window.state.pred.zone }
    window.panel.update(window.state, false)
  })
  await expect(page.getByTestId('cam-status')).toContainText('agrees')
  await expect(page.getByTestId('cam-status')).not.toContainText('zone ')
  await expect(page.getByTestId('cam-status')).toHaveCSS('color', 'rgb(230, 232, 235)')
  await page.evaluate(() => { window.state.cam = 'off'; window.panel.update(window.state, false) })
  await expect(page.getByTestId('camera-unplug')).toBeVisible()
  await page.clock.fastForward(8001)
  await expect(page.getByTestId('camera-unplug')).toBeHidden()
})
