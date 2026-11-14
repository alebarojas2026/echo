const { test, expect } = require('@playwright/test')
const path = '/src/hud/'
for (const width of [320, 768, 1024, 1440]) {
  test(`shows the panels at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto(path + '?source=sim')
    for (const [id, text] of Object.entries({
      'source-badge': 'FAKE', 'cam-status': 'CAMERA OFF', 'narrator-text': 'The room occupant has stopped moving.',
      'narrator-source': 'template', 'alert-banner': 'No-movement alert',
      'advice-text': 'An obstruction is blocking the link. Move the router 30 cm west.',
    })) await expect(page.getByTestId(id)).toHaveText(text)
    for (const id of ['before-dbm', 'after-dbm', 'zone-score', 'person-object-score', 'train-seconds',
      'ms-per-decision', 'watts', 'bytes-out', 'images-stored', 'models-count', 'pred-kind', 'pred-zone']) {
      await expect(page.getByTestId(id)).toHaveText('__')
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  })
}
for (const source of ['live', 'replay']) {
  test(`shows ${source} and check-in`, async ({ page }) => {
    await page.goto(path + `?source=${source}&movement=check-in&cam=stalled&no-advice`)
    await expect(page.getByTestId('source-badge')).toHaveText(source.toUpperCase())
    await expect(page.getByTestId('checkin-toast')).toHaveText('Check-in received')
    await expect(page.getByTestId('alert-banner')).toBeEmpty()
    await expect(page.getByTestId('cam-status')).toHaveText('CAMERA STALLED')
    await expect(page.getByTestId('advice-text')).toHaveText('__')
  })
}
