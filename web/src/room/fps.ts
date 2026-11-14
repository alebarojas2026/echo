import type { RoomView } from './view'

// ?fps=1 draws every frame (normally the room only draws when something changes) and shows the measured
// frame rate, so the Pi 5 screen can be checked against the 30 fps target. Nothing here is a claim:
// it prints what this browser measured, now.

export interface FpsStats {
  now: number
  min: number
  avg: number
  seconds: number
}

/** Folds one-second frame counts into running stats. The first second is skipped as warm-up. */
export class FpsTally {
  private samples: number[] = []
  private warm = false

  add(fps: number): FpsStats | null {
    if (!this.warm) {
      this.warm = true
      return null
    }
    this.samples.push(fps)
    const sum = this.samples.reduce((a, b) => a + b, 0)
    return { now: fps, min: Math.min(...this.samples), avg: sum / this.samples.length, seconds: this.samples.length }
  }
}

export function startFpsMeter(view: RoomView) {
  const el = document.createElement('output')
  el.className = 'room-fps'
  el.textContent = 'measuring fps…'
  view.host.append(el)
  const tally = new FpsTally()
  let frames = 0
  let since = performance.now()
  view.addAnimator(() => {
    frames++
    const now = performance.now()
    if (now - since >= 1000) {
      const stats = tally.add((frames * 1000) / (now - since))
      frames = 0
      since = now
      if (stats) {
        const { width, height } = view.renderer.domElement
        el.textContent = `${stats.now.toFixed(0)} fps · min ${stats.min.toFixed(0)} · avg ${stats.avg.toFixed(1)} over ${stats.seconds} s · ${width}x${height}`
        view.host.dataset.fps = stats.now.toFixed(1)
        view.host.dataset.fpsMin = stats.min.toFixed(1)
        view.host.dataset.fpsAvg = stats.avg.toFixed(1)
      }
    }
    return true // keep drawing every frame while measuring
  })
}
