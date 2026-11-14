import './hud.css'
import { connectHud, type HudFeed } from './feed'
import type { HudState } from './state'

function measurement(value: number | null | undefined, unit = '') {
  return Number.isFinite(value) ? `${value}${unit}` : '__'
}

export function renderHud(root: HTMLElement, state: HudState) {
  root.classList.add('radio-hud')
  if (!root.querySelector('.hud-header')) {
    root.innerHTML = `
      <header class="hud-header">
        <h1>Radio Sight</h1>
        <div class="hud-indicators">
          <span data-testid="source-badge" class="hud-badge"></span>
          <span data-testid="cam-status" class="hud-camera"></span>
        </div>
      </header>
      <div class="hud-grid">
        <section class="hud-card hud-narrator" aria-labelledby="hud-narrator">
          <h2 id="hud-narrator">Narrator</h2>
          <p data-testid="narrator-text" aria-live="polite"></p>
          <small data-testid="narrator-source"></small>
        </section>
        <section class="hud-card hud-movement" aria-labelledby="hud-movement">
          <h2 id="hud-movement">Room status</h2>
          <p data-testid="no-data" role="status" hidden>NO DATA</p>
          <p data-testid="sensor-blind" role="status" hidden>SENSOR BLIND</p>
          <p data-testid="alert-banner" role="status"></p>
          <p data-testid="checkin-toast" role="status"></p>
          <small data-testid="alert-zone"></small>
          <dl class="hud-details">
            <div><dt>Kind</dt><dd data-testid="pred-kind"></dd></div>
            <div><dt>Motion</dt><dd data-testid="pred-motion"></dd></div>
            <div><dt>Zone</dt><dd data-testid="pred-zone"></dd></div>
            <div><dt>Possible zones</dt><dd data-testid="pred-zone-set"></dd></div>
            <div><dt>Radio links</dt><dd data-testid="why-links"></dd></div>
          </dl>
        </section>
        <section class="hud-card hud-advice" aria-labelledby="hud-advice">
          <h2 id="hud-advice">Router placement</h2>
          <p data-testid="advice-text"></p>
          <small>Router spot <span data-testid="router-spot"></span></small>
          <dl>
            <div><dt>Before (dBm)</dt><dd data-testid="before-dbm"></dd></div>
            <div><dt>After (dBm)</dt><dd data-testid="after-dbm"></dd></div>
          </dl>
        </section>
      </div>
      <section class="hud-proof hud-card" aria-labelledby="hud-proof">
        <h2 id="hud-proof">Proof</h2>
        <dl>
          <div><dt>Radio vs camera agreement</dt><dd data-testid="zone-score"></dd></div>
          <div><dt>Person vs object agreement</dt><dd data-testid="person-object-score"></dd></div>
          <div><dt>Train seconds</dt><dd data-testid="train-seconds"></dd></div>
          <div><dt>ms per decision</dt><dd data-testid="ms-per-decision"></dd></div>
          <div><dt>Watts</dt><dd data-testid="watts"></dd></div>
          <div><dt>Bytes out</dt><dd data-testid="bytes-out"></dd></div>
          <div><dt>Images stored</dt><dd data-testid="images-stored"></dd></div>
          <div><dt>Models on board</dt><dd data-testid="models-count"></dd></div>
        </dl>
      </section>
    `
  }

  const blind = state.feedStatus === 'blind'
  const stale = state.feedStatus === 'stale'
  root.querySelector('[data-testid="no-data"]')?.toggleAttribute('hidden', !stale)
  root.querySelector('[data-testid="sensor-blind"]')?.toggleAttribute('hidden', !blind)
  const pred = state.prediction
  const values = {
    'source-badge': state.source,
    'cam-status': state.camera,
    'narrator-text': state.narration?.text ?? '__',
    'narrator-source': state.narration?.source ?? '',
    'alert-banner': blind || stale ? '' : state.alert,
    'alert-zone': blind || stale || state.alertZone == null ? '' : `Zone ${state.alertZone}`,
    'checkin-toast': !blind && !stale && state.checkin ? 'Check-in received' : '',
    'pred-kind': pred?.kind ?? '__',
    'pred-motion': pred?.motion ?? '__',
    'pred-zone': measurement(pred?.zone),
    'pred-zone-set': pred?.zone_set.join(', ') || '__',
    'why-links': pred?.why.join(', ') || '__',
    'advice-text': state.advice?.text ?? '__',
    'router-spot': state.router,
    'before-dbm': measurement(state.advice?.before_dbm, ' dBm'),
    'after-dbm': measurement(state.advice?.after_dbm, ' dBm'),
    'zone-score': measurement(state.proof.agreement, '%'),
    'person-object-score': measurement(state.proof.personObjectScore, '%'),
    'train-seconds': measurement(state.proof.trainSeconds, ' s'),
    'ms-per-decision': measurement(state.proof.decisionMs, ' ms'),
    watts: measurement(state.proof.watts, ' W'),
    'bytes-out': measurement(state.proof.bytesOut, ' bytes out'),
    'images-stored': measurement(state.proof.images, ' images'),
    'models-count': measurement(state.proof.models),
  }
  for (const [id, value] of Object.entries(values)) {
    const field = root.querySelector(`[data-testid="${id}"]`)
    if (field && field.textContent !== value) field.textContent = value
  }
  root.dataset.movement = state.checkin ? 'check-in' : state.movement
}

export function mountHud(root: HTMLElement, feed: HudFeed | null) {
  return connectHud(root, feed, renderHud)
}
