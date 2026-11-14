export type FeedSource = 'live' | 'sim' | 'replay'

export type ScreenState = {
  v: 2
  type: 'state'
  t: number
  seq: number
  src: FeedSource
  links?: { rate_hz: number | null }[]
  cam: 'on' | 'off' | 'stalled'
  router: string
  health: { status: 'ok' | 'degraded' | 'blind' }
  pred: {
    kind: 'person' | 'object' | 'none'
    zone: number
    zone_set: number[]
    motion: string
    why: string[]
  } | null
  alert: { state: 'none' | 'counting' | 'check_on'; zone: number | null; still_s: number | null; limit_s: number | null }
  checkin: { t: number; link: string } | null
  advice: { text: string; before_dbm: number | null; after_dbm: number | null } | null
  narration: { text: string; source: 'llm' | 'template' } | null
  model: { train_s: number | null; ms_per_decision: number | null } | null
}

type Score = { correct: number | null; total: number | null }

export type Proof = {
  zone: Score | null
  person_vs_object: Score | null
  train_s: number | null
  ms_per_decision: { p50: number | null; p95: number | null } | null
  watts: { radio_only: number | null } | null
  bytes_out: number | null
  images_stored: number | null
  models_on_board: number | null
}

const sourceLabels = { live: 'LIVE', sim: 'FAKE', replay: 'REPLAY' }
const cameraLabels = { on: 'CAMERA ON', off: 'CAMERA OFF', stalled: 'CAMERA STALLED' }
const alertLabels = { none: '', counting: 'Monitoring stillness', check_on: 'No-movement alert' }

function agreement(score: Score | null | undefined) {
  if (score?.correct == null || !score.total) return null
  return Math.round(100 * score.correct / score.total)
}

export function adaptHudState(state: ScreenState | null, proof: Proof | null, receivedAt = Date.now(), now = Date.now()) {
  const feedStatus = !state || now - receivedAt > 1000 ? 'stale' : state.health.status
  return {
    feedStatus,
    source: state?.src === 'live' && !state.links?.some(link => (link.rate_hz ?? 0) > 0) ? '__' : state ? sourceLabels[state.src] : '__',
    camera: state ? cameraLabels[state.cam] : '__',
    movement: state?.alert.state ?? 'none',
    alert: alertLabels[state?.alert.state ?? 'none'],
    alertZone: state && state.alert.state !== 'none' ? state.alert.zone : null,
    checkin: state?.alert.state === 'none' && state.checkin !== null,
    narration: state?.narration ?? null,
    advice: state?.advice ?? null,
    router: state?.router ?? '__',
    prediction: feedStatus === 'blind' || feedStatus === 'stale' ? null : state?.pred ?? null,
    proof: {
      agreement: agreement(proof?.zone),
      personObjectScore: agreement(proof?.person_vs_object),
      trainSeconds: proof ? proof.train_s : state?.model?.train_s ?? null,
      decisionMs: proof ? proof.ms_per_decision?.p50 ?? null : state?.model?.ms_per_decision ?? null,
      watts: proof?.watts?.radio_only ?? null,
      bytesOut: proof?.bytes_out ?? null,
      images: proof?.images_stored ?? null,
      models: proof?.models_on_board ?? null,
    },
  }
}

export type HudState = ReturnType<typeof adaptHudState>
