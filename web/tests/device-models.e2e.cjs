const { test, expect } = require('@playwright/test')
const path = require('node:path'), fs = require('node:fs')
const desk = require('./fixtures/desk-layout.json')
for (const [width,height] of [[1920,1080],[1440,900]]) test(`five desk models retain live hearing and tamper at ${width}`, async ({ page }) => {
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  page.on('console', e => { if (e.type() === 'warning' && e.text().includes('could not load')) errors.push(e.text()) })
  // The feed is local; development reload messages must not replace it mid-test.
  await page.routeWebSocket('**', socket => {
    const server = socket.connectToServer()
    server.onMessage(message => {
      const type = typeof message === 'string' ? JSON.parse(message).type : ''
      if (type !== 'full-reload' && type !== 'update') socket.send(message)
    })
    socket.onMessage(message => server.send(message))
  })
  await page.setViewportSize({ width, height })
  await page.clock.install({ time: new Date('2026-01-01T00:00:00Z') })
  await page.clock.pauseAt(new Date('2026-01-01T00:00:01Z'))
  await page.goto('/tests/arrival-harness.html?scan=0&layout=desk')
  await page.evaluate(async () => (await import('/src/room/devices.ts')).devicesLoaded())
  const models = () => page.evaluate(() => window.room.stage.group.children.filter(o => o.name.startsWith('device-')).map(o => ({ name: o.name, visible: o.visible })))
  expect((await models()).map(o => o.name).sort()).toEqual(['device-beacon','device-beacon','device-pi5','device-pi5','device-unoq'])
  expect((await models()).every(o => !o.visible)).toBe(true)
  await page.clock.runFor(400)
  await page.evaluate(() => window.arrival.update('still'))
  await page.clock.runFor(6000)
  expect((await models()).every(o => o.visible)).toBe(true)
  await expect(page.locator('#room')).toHaveAttribute('data-devices', desk.nodes.map(n => n.id).join(','))
  const top = await page.evaluate(() => {
    const device = window.room.stage.group.children.find(o => o.name === 'device-pi5')
    const canvas = document.querySelector('#room canvas').getBoundingClientRect()
    let top = Infinity
    device.getObjectByName('head').traverse(m => {
      if (!m.geometry) return
      m.geometry.computeBoundingBox()
      const { min, max } = m.geometry.boundingBox
      for (let i = 0; i < 8; i++) {
        const p = min.clone().set(i & 1 ? max.x : min.x, i & 2 ? max.y : min.y, i & 4 ? max.z : min.z)
        m.localToWorld(p).project(window.room.view.camera)
        top = Math.min(top, canvas.y + (1 - p.y) / 2 * canvas.height)
      }
    })
    return top
  })
  const label = await page.locator('.room-label--node').filter({ hasText: /^Pi A$/ }).boundingBox()
  expect(label.y + label.height).toBeLessThan(top)
  if (process.env.HUD_SCREENSHOTS) {
    fs.mkdirSync(process.env.HUD_SCREENSHOTS, { recursive: true })
    for (const scene of ['still','object','blind','empty']) {
      await page.evaluate(scene => window.arrival.update(scene), scene)
      await page.clock.runFor(700)
      await page.screenshot({ path: path.join(process.env.HUD_SCREENSHOTS, `${width}-${scene}.png`) })
    }
  }
  await page.evaluate(() => window.arrival.update('still', { armed: true, tamper: ['east'] }))
  await page.clock.runFor(300)
  await expect(page.locator('#room')).toHaveAttribute('data-tamper', 'east')
  await expect(page.locator('.room-label--node-tamper')).toContainText('East beacon')
  const faults = await page.evaluate(() => window.room.stage.group.children.filter(o => o.name.startsWith('device-')).map(o => {
    const values = []; o.traverse(m => { if (m.material?.uniforms?.uFault) values.push(m.material.uniforms.uFault.value) }); return values.some(v => v === 1)
  }))
  expect(faults.filter(Boolean)).toHaveLength(1)
  if (process.env.HUD_SCREENSHOTS) await page.screenshot({ path: path.join(process.env.HUD_SCREENSHOTS, `${width}-alert.png`) })
  const silence = () => page.evaluate(() => window.arrival.update('empty', { tamper: [], links: [] }))
  await silence()
  await page.clock.runFor(2600)
  await silence()
  await page.clock.runFor(150)
  await expect(page.locator('#room')).toHaveAttribute('data-devices-lost', desk.nodes.map(n => n.id).join(','))
  await expect(page.locator('.room-label--node-lost')).toHaveCount(5)
  const alpha = await page.evaluate(() => {
    const values = []; window.room.stage.group.children.filter(o => o.name.startsWith('device-')).forEach(o => o.traverse(m => { if (m.material?.uniforms?.uAlpha) values.push(m.material.uniforms.uAlpha.value) })); return values
  })
  expect(alpha.every(a => a > 0 && a < 1)).toBe(true)
  expect(errors).toEqual([])
})
