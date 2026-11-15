export class NumberCadence {
  private at = -Infinity
  take(now: number) {
    if (now - this.at < 1000) return false
    this.at = now
    return true
  }
}

export class ReadingHold {
  private text = ''
  private since = -Infinity
  update(next: string, now: number, clear = false) {
    if (clear || !this.text || now - this.since >= 4000) {
      if (this.text !== next) this.since = now
      this.text = next
    }
    return this.text
  }
}
