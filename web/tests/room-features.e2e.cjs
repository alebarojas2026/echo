const { test, expect } = require('@playwright/test')
const fs = require('node:fs'), path = require('node:path')
const desk = require('./fixtures/desk-layout.json')
const shots = process.env.HUD_SCREENSHOTS

// A small floor mesh stands in for the private hall scan; no scan files are needed.
const vertices = new Float32Array([-10,0,-8, 10,0,-8, -10,0,8, -10,0,8, 10,0,-8, 10,0,8])
const floor = { asset: { version: '2.0' }, scene: 0, scenes: [{ nodes: [0] }], nodes: [{ mesh: 0 }],
  meshes: [{ primitives: [{ attributes: { POSITION: 0 } }] }],
  buffers: [{ byteLength: vertices.byteLength, uri: 'data:application/octet-stream;base64,' + Buffer.from(vertices.buffer).toString('base64') }],
  bufferViews: [{ buffer: 0, byteLength: vertices.byteLength }],
  accessors: [{ bufferView: 0, componentType: 5126, count: 6, type: 'VEC3', min: [-10,0,-8], max: [10,0,8] }] }

async function setup(page, width, height) {
  const layout = structuredClone(desk)
  let fit = { offset_m: [0,0], yaw_deg: 0, scale: 1, cut_m: 1.4, floor_m: 0 }
  const saved = { fits: [], beacons: [] }, errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.setViewportSize({ width, height })
  await page.clock.install({ time: new Date('2026-01-01T00:00:00Z') })
  await page.clock.pauseAt(new Date('2026-01-01T00:00:01Z'))
  await page.route('**/nodes.json', route => route.fulfill({ json: layout }))
  await page.route('**/test-hall.gltf', route => route.fulfill({ json: floor }))
  await page.route('**/__room-scan', route => {
    if (route.request().method() === 'POST') {
      fit = route.request().postDataJSON(); saved.fits.push(fit)
      return route.fulfill({ json: { ok: true } })
    }
    return route.fulfill({ json: { hi: '/test-hall.gltf', lo: '/test-hall.gltf', fit } })
  })
  await page.route('**/__hall-beacons', route => {
    const positions = route.request().postDataJSON()
    saved.beacons.push(positions)
    for (const position of positions) Object.assign(layout.hall.beacons.find(b => b.node === position.node), position)
    return route.fulfill({ json: { ok: true } })
  })
  return { saved, errors }
}
async function capture(page, name) {
  if (shots) { fs.mkdirSync(shots, { recursive: true }); await page.screenshot({ path: path.join(shots, name + '.png') }) }
}
for (const [width, height] of [[1920,1080], [1440,900]]) {
  test(`devices appear only while heard at ${width}`, async ({ page }) => {
    const { errors } = await setup(page, width, height)
    await page.goto('/tests/room-harness.html?mock=power&scan=0')
    const room = page.locator('#room')
    await page.clock.runFor(200)
    await expect(room).toHaveAttribute('data-devices', '')
    await page.clock.runFor(2800)
    expect((await room.getAttribute('data-devices')).split(',').sort()).toEqual(desk.nodes.map(n => n.id).sort())
    await capture(page, `${width}-heard`)
    await page.clock.runFor(6500)
    await expect(room).toHaveAttribute('data-devices-lost', 'east')
    await expect(page.locator('.room-label').filter({ hasText: 'East beacon' })).toContainText('not heard')
    await capture(page, `${width}-lost`)
    await page.clock.runFor(5000)
    await expect(room).toHaveAttribute('data-devices-lost', '')
    expect((await room.getAttribute('data-devices')).split(',')).toContain('east')
    expect(errors).toEqual([])
  })
  test(`place new beacons, move the kit and save across reload at ${width}`, async ({ page }) => {
    const { saved, errors } = await setup(page, width, height)
    await page.goto('/tests/room-harness.html?mock=power&align=1')
    const room = page.locator('#room')
    await expect(room).toHaveAttribute('data-align', 'on')
    await page.clock.runFor(1500)
    await expect(room).toHaveAttribute('data-hall-waiting', 'h')
    await expect(page.locator('.room-tray')).toContainText('1 new beacon: H')
    await page.clock.runFor(3500)
    await expect(page.locator('.room-tray')).toContainText('2 new beacons: H, J')
    await capture(page, `${width}-tray`)
    await page.keyboard.press('Tab')
    await expect(room).toHaveAttribute('data-selected', 'h')
    for (let i = 0; i < 3; i++) await page.keyboard.press('Shift+ArrowRight')
    await page.keyboard.press('Shift+ArrowUp')
    await expect(room).toHaveAttribute('data-hall-beacons', 'h')
    const chip = page.locator('.room-tray-chip').filter({ hasText: 'J' })
    const box = await chip.boundingBox(), canvas = await page.locator('#room canvas').boundingBox()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.down()
    await page.mouse.move(canvas.x + canvas.width * .65, canvas.y + canvas.height * .55, { steps: 6 })
    await page.mouse.up()
    await expect(room).toHaveAttribute('data-hall-beacons', 'h,j')
    await page.keyboard.press('Escape')
    await page.keyboard.press('ArrowRight')
    await page.keyboard.press('q')
    await page.keyboard.press('s')
    await expect(page.locator('.room-align-status')).toContainText('Saved to')
    expect(saved.fits).toHaveLength(1)
    expect(saved.fits[0]).toMatchObject({ offset_m: [.02,0], yaw_deg: 1 })
    expect(saved.beacons).toHaveLength(1)
    expect(saved.beacons[0][0].xyz_m).toEqual([desk.frame.size_m[0] / 2 + 3, desk.frame.size_m[1] + 3, 1])
    expect(saved.beacons[0][1].xyz_m.every(Number.isFinite)).toBe(true)
    await capture(page, `${width}-placed`)
    await page.reload()
    await expect(room).toHaveAttribute('data-align', 'on')
    await page.clock.runFor(5000)
    await expect(room).toHaveAttribute('data-hall-beacons', 'h,j')
    await expect(page.locator('.room-tray')).toBeHidden()
    await expect(page.locator('.room-align-fit')).toContainText('East +0.02 m')
    await expect(page.locator('.room-align-fit')).toContainText('Turn +1.0°')
    expect(errors).toEqual([])
  })
  test(`arrival holds the hall, then flies in; H flies back at ${width}`, async ({ page }) => {
    const { errors } = await setup(page, width, height)
    await page.goto('/tests/arrival-harness.html')
    const room = page.locator('#room')
    await expect(room).toHaveAttribute('data-view', 'hall')
    await page.clock.runFor(5000)
    await expect(room).toHaveAttribute('data-view', 'hall')
    await capture(page, `${width}-hall`)
    await page.evaluate(() => window.arrival.update('still'))
    await page.clock.runFor(2800)
    await expect(room).toHaveAttribute('data-view', 'flying')
    await page.clock.runFor(5000)
    await expect(room).toHaveAttribute('data-view', 'square')
    await expect(page.locator('.hud-arrival')).toBeHidden()
    await capture(page, `${width}-close`)
    await page.keyboard.press('h')
    await page.clock.runFor(100)
    await expect(room).toHaveAttribute('data-view', 'flying')
    await page.clock.runFor(3200)
    await expect(room).toHaveAttribute('data-view', 'hall')
    expect(errors).toEqual([])
  })
}

