const { test, expect } = require('@playwright/test')

const panel = '/src/hud/'

for (const width of [320, 768, 1024, 1440]) {
  test(`shows every HUD panel at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.goto(panel)

    await expect(page.getByRole('heading', { name: 'Radio Sight' })).toBeVisible()
    await expect(page.getByText('FAKE', { exact: true })).toBeVisible()
    await expect(page.getByText('CAMERA OFF', { exact: true })).toBeVisible()
    await expect(page.getByRole('status')).toHaveText('No movement detected')
    await expect(page.getByRole('region', { name: 'Narrator' }).locator('p'))
      .toHaveText('The radio detects someone in the room who has stopped moving.')

    const advice = page.getByRole('region', { name: 'Router placement' })
    await expect(advice.getByText('Move the router 30 cm north')).toBeVisible()
    for (const label of ['Before (dB)', 'After (dB)']) {
      await expect(advice.getByText(label, { exact: true })).toBeVisible()
    }
    await expect(advice.locator('dd')).toHaveText(['__', '__'])

    const proof = page.getByRole('region', { name: 'Proof' })
    for (const label of ['Radio vs camera agreement', 'Train seconds', 'ms per decision', 'Watts']) {
      await expect(proof.getByText(label, { exact: true })).toBeVisible()
    }
    await expect(proof.locator('dd')).toHaveText(['__', '__', '__', '__', '0 bytes out', '0 images'])
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    expect(errors).toEqual([])
  })
}

for (const source of ['LIVE', 'REPLAY']) {
  test(`renders ${source} and the received check-in`, async ({ page }) => {
    await page.goto(`${panel}?source=${source}&movement=check-in`)
    await expect(page.getByText(source, { exact: true })).toBeVisible()
    await expect(page.getByRole('status')).toHaveText('Check-in received')
    await expect(page.getByRole('region', { name: 'Narrator' }).locator('p'))
      .toHaveText('The room occupant checked in.')
  })
}
