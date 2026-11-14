import './hud.css'
import type { HudState } from './state'

function measurement(value: number | null, unit: string, separator = ' ') {
  return Number.isFinite(value) ? `${value}${separator}${unit}` : '__'
}

export function renderHud(root: HTMLElement, state: HudState) {
  root.classList.add('radio-hud')
  if (!root.querySelector('.hud-header')) {
    root.innerHTML = `
      <header class="hud-header">
        <h1>Radio Sight</h1>
        <div class="hud-indicators">
          <span data-value="source" class="hud-badge"></span>
          <span data-value="camera" class="hud-camera"></span>
        </div>
      </header>
      <div class="hud-grid">
        <section class="hud-card hud-narrator" aria-labelledby="hud-narrator">
          <h2 id="hud-narrator">Narrator</h2>
          <p data-value="narration" aria-live="polite"></p>
        </section>
        <section class="hud-card hud-movement" aria-labelledby="hud-movement">
          <h2 id="hud-movement">Room status</h2>
          <p data-value="movement" role="status"></p>
        </section>
        <section class="hud-card hud-advice" aria-labelledby="hud-advice">
          <h2 id="hud-advice">Router placement</h2>
          <p>Move the router 30 cm north</p>
          <dl>
            <div><dt>Before (dB)</dt><dd data-value="before"></dd></div>
            <div><dt>After (dB)</dt><dd data-value="after"></dd></div>
          </dl>
        </section>
      </div>
      <section class="hud-proof hud-card" aria-labelledby="hud-proof">
        <h2 id="hud-proof">Proof</h2>
        <dl>
          <div><dt>Radio vs camera agreement</dt><dd data-value="agreement"></dd></div>
          <div><dt>Train seconds</dt><dd data-value="trainSeconds"></dd></div>
          <div><dt>ms per decision</dt><dd data-value="decisionMs"></dd></div>
          <div><dt>Watts</dt><dd data-value="watts"></dd></div>
          <div><dt>Network</dt><dd data-value="bytesOut"></dd></div>
          <div><dt>Camera storage</dt><dd data-value="images"></dd></div>
        </dl>
      </section>
    `
  }

  const movementLabels = {
    'no-movement': 'No movement detected',
    'check-in': 'Check-in received',
    normal: 'Monitoring movement',
  }
  const values = {
    source: state.source,
    camera: state.camera === 'off' ? 'CAMERA OFF' : 'CAMERA ON',
    narration: state.narration,
    movement: movementLabels[state.movement],
    before: measurement(state.signal.before, 'dB'),
    after: measurement(state.signal.after, 'dB'),
    agreement: measurement(state.proof.agreement, '%', ''),
    trainSeconds: measurement(state.proof.trainSeconds, 's'),
    decisionMs: measurement(state.proof.decisionMs, 'ms'),
    watts: measurement(state.proof.watts, 'W'),
    bytesOut: measurement(state.proof.bytesOut, 'bytes out'),
    images: measurement(state.proof.images, 'images'),
  }

  for (const [key, value] of Object.entries(values)) {
    const field = root.querySelector(`[data-value="${key}"]`)
    if (field && field.textContent !== value) field.textContent = value
  }
  root.dataset.movement = state.movement
}
