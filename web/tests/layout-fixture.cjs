const { test } = require('@playwright/test')
const fs = require('node:fs')
const path = require('node:path')
const layout = JSON.parse(fs.readFileSync(process.env.HUD_LAYOUT_FILE || path.resolve(__dirname, '../../radio/nodes.json'), 'utf8').replace(/^\uFEFF/, ''))
test.beforeEach(async ({ page }) => {
  await page.route('**/nodes.json', route => route.fulfill({ json: layout }))
})
const zone = layout.zones.at(-1)
module.exports = { layout, zone, still: zone.name === 'Right' ? 'Still on the right' : 'Still in the bathroom', place: zone.name === 'Right' ? 'on the right' : 'in the bathroom' }
