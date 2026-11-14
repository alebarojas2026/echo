const { test, expect } = require('@playwright/test')
const path = '/src/hud/index.html'
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

test('shows blind while the feed is fresh, then no data when it goes stale', async ({ page }) => {
  await page.clock.install()
  await page.goto(path + '?blind&pause')
  await expect(page.getByTestId('sensor-blind')).toBeVisible()
  await expect(page.getByTestId('no-data')).toBeHidden()
  await expect(page.getByTestId('alert-banner')).toBeEmpty()
  await page.clock.fastForward(1001)
  await expect(page.getByTestId('no-data')).toBeVisible()
  await expect(page.getByTestId('sensor-blind')).toBeHidden()
  await expect(page.getByTestId('pred-kind')).toHaveText('__')
})
test('reads proof.json and preserves missing metrics and measured zero', async ({ page }) => {
  await page.route('**/proof.json', route => route.fulfill({ json: {
    zone: { correct: null, total: null }, person_vs_object: null, train_s: null,
    ms_per_decision: { p50: null, p95: null }, watts: { radio_only: null },
    bytes_out: null, images_stored: null, models_on_board: 0,
  } }))
  await page.goto(path)
  await expect(page.getByTestId('models-count')).toHaveText('0')
  for (const id of ['zone-score', 'person-object-score', 'train-seconds', 'ms-per-decision',
    'watts', 'bytes-out', 'images-stored']) await expect(page.getByTestId(id)).toHaveText('__')
})
test('controls emit v2 commands with selected arguments', async ({ page }) => {
  await page.addInitScript(() => {
    window.commands = []
    document.addEventListener('hud-command', event => window.commands.push(event.detail))
  })
  await page.goto(path)
  await page.getByTestId('train-button').click()
  await page.getByRole('button', { name: 'Baseline', exact: true }).click()
  await page.getByLabel('Session').fill('demo-session')
  await page.getByLabel('Purpose').selectOption('demo')
  await page.getByLabel('Walker').fill('demo-walker')
  await page.getByRole('button', { name: 'Start recording' }).click()
  await page.getByRole('button', { name: 'Stop recording' }).click()
  await page.getByLabel('Label mode', { exact: true }).selectOption('object')
  await page.getByRole('button', { name: 'Set label mode' }).click()
  await page.getByLabel('New router spot').selectOption('S-E30')
  await page.getByRole('button', { name: 'Router moved' }).click()
  await page.getByRole('button', { name: 'Router home' }).click()
  await page.getByRole('button', { name: 'Reset alert' }).click()
  await page.getByRole('button', { name: 'Reset demo' }).click()
  expect(await page.evaluate(() => window.commands)).toEqual([
    ['train', {}], ['baseline', {}],
    ['record_start', { session: 'demo-session', purpose: 'demo', walker: 'demo-walker' }],
    ['record_stop', {}], ['label_mode', { mode: 'object' }], ['router_moved', { spot: 'S-E30' }],
    ['router_home', {}], ['reset_alert', {}], ['reset', {}],
  ].map(([cmd, args]) => ({ v: 2, type: 'cmd', cmd, args })))
})

test('mounts in a stale state when the shell has no feed', async ({ page }) => {
  await page.goto('/src/hud/index.html')
  await page.evaluate(async () => {
    const { mountHud } = await import('/src/hud/index.ts')
    mountHud(document.querySelector('main'), null)
  })
  await expect(page.getByTestId('no-data')).toBeVisible()
  await expect(page.getByTestId('pred-kind')).toHaveText('__')
})

test('mounted controls send commands and proof refresh stops on disposal', async ({ page }) => {
  let count = 0
  await page.route('**/proof.json', route => route.fulfill({ json: { bytes_out: ++count } }))
  await page.clock.install()
  await page.goto(path)
  await page.evaluate(async () => {
    const { mountHud } = await import('/src/hud/index.ts')
    const { mockFeed } = await import('/src/hud/mock.ts')
    document.body.innerHTML = '<main></main>'
    window.sent = []
    window.dispose = mountHud(document.querySelector('main'), {
      subscribe(fn) { fn({ state: mockFeed(new URLSearchParams()).state, stale: false }); return () => {} },
      send(cmd, args) { window.sent.push({ cmd, args }) },
    })
  })
  await expect(page.getByTestId('bytes-out')).toHaveText('1 bytes out')
  await page.locator('summary').click()
  await page.getByTestId('train-button').click()
  expect(await page.evaluate(() => window.sent)).toEqual([{ cmd: 'train', args: {} }])
  await page.clock.fastForward(30000)
  await expect(page.getByTestId('bytes-out')).toHaveText('2 bytes out')
  await page.evaluate(() => window.dispose())
  await page.clock.fastForward(30000)
  expect(count).toBe(2)
})

