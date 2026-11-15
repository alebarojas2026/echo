const { test, expect } = require('@playwright/test')

test('baseline keeps the model only when requested; forgetting requires confirmation', async ({ page }) => {
  await page.addInitScript(() => {
    window.commands = []
    document.addEventListener('hud-command', event => window.commands.push(event.detail))
  })
  await page.goto('/src/hud/index.html?op=1')
  const keep = page.getByRole('button', { name: 'New baseline, keep the model', exact: true })
  const forget = page.getByRole('button', { name: 'New place: baseline and forget the model', exact: true })
  let dialogs = 0
  page.on('dialog', () => dialogs++)
  await keep.click()
  expect(dialogs).toBe(0)
  const kept = { v: 2, type: 'cmd', cmd: 'baseline', args: { keep_model: true } }
  expect(await page.evaluate(() => window.commands)).toEqual([kept])
  page.once('dialog', async dialog => {
    expect(dialog.type()).toBe('confirm')
    expect(dialog.message()).toContain('cannot be undone')
    await dialog.dismiss()
  })
  await forget.click()
  expect(await page.evaluate(() => window.commands)).toEqual([kept])
  page.once('dialog', dialog => dialog.accept())
  await forget.click()
  expect(await page.evaluate(() => window.commands)).toEqual([kept, { v: 2, type: 'cmd', cmd: 'baseline', args: {} }])
  expect(dialogs).toBe(2)
  await page.goto('/?mock=still')
  await expect(keep).toBeHidden()
  await page.keyboard.press('o')
  // The recording controls sit folded under the presenter's own buttons.
  await page.getByText('Advanced recording controls').click()
  await expect(keep).toBeVisible()
  await expect(forget).toBeVisible()
})
