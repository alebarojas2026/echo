// The hidden test mirror (CONTRACTS.md section 8): what the 3D room shows, as plain DOM.
// <ul data-testid="beams"> holds one <li data-testid="beam-<link id>"> per link and one <li data-testid="xray">.

export class Mirror {
  readonly list: HTMLUListElement
  private readonly items = new Map<string, HTMLLIElement>()

  constructor(host: HTMLElement) {
    this.list = document.createElement('ul')
    this.list.dataset.testid = 'beams'
    this.list.className = 'visually-hidden'
    this.list.setAttribute('aria-label', 'Radio links')
    host.append(this.list)
  }

  /** Sets the item's data attributes (null removes one) and its readable text. */
  set(testid: string, data: Record<string, string | null>, text: string) {
    let li = this.items.get(testid)
    if (!li) {
      li = document.createElement('li')
      li.dataset.testid = testid
      this.list.append(li)
      this.items.set(testid, li)
    }
    for (const [key, value] of Object.entries(data)) {
      const attr = `data-${key}`
      if (value === null) li.removeAttribute(attr)
      else if (li.getAttribute(attr) !== value) li.setAttribute(attr, value)
    }
    if (li.textContent !== text) li.textContent = text
  }
}
