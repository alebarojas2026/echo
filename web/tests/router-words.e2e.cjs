const { test, expect } = require('@playwright/test')
test('router locations read as words in both panel views', async ({ page }) => {
  await page.goto('/src/hud/index.html')
  const words = await page.evaluate(async () => {
    const { routerWords } = await import('/src/hud/router-words.ts')
    return ['S-home', 'S-W30', 'S-E30', 'unknown'].map(routerWords)
  })
  expect(words).toEqual(['Router at home', 'Router 30 cm west', 'Router 30 cm east', 'Router location unavailable'])
  for (const [spot, text] of [['S-home', words[0]], ['S-W30', words[1]], ['S-E30', words[2]]]) {
    await page.evaluate(async spot => {
      const { renderHud } = await import('/src/hud/index.ts')
      const { mockFeed } = await import('/src/hud/mock.ts')
      const { adaptHudState } = await import('/src/hud/state.ts')
      const data = mockFeed(new URLSearchParams())
      data.state.router = spot
      document.body.innerHTML = '<main></main>'
      renderHud(document.querySelector('main'), adaptHudState(data.state, data.proof))
    }, spot)
    await expect(page.getByTestId('router-spot')).toHaveText(text)
  }
  await page.goto('/?mock=still&op=1')
  await expect(page.getByTestId('router-spot')).toHaveText('Router at home')
})
