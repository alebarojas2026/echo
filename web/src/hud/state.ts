export type FeedSource = 'live' | 'sim' | 'replay'

export type ScreenState = {
  v: 2
  type: 'state'
  t: number
  seq: number
  src: FeedSource
  cam: 'on' | 'off' | 'stalled' | 'unknown'
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
  model: { train_s: number | null; ms_per_decision: number | null }
}

type Score = { correct: number | null; total: number | null }

export type Proof = {
  zone: Score | null
  person_vs_object: Score | null
  /** Somebody there or nobody, per second on held-out cycles; always_empty_correct is the always-"nobody" score on the same seconds (#656). */
  presence?: { correct: number | null; total: number | null; always_empty_correct: number | null; cycles: number | null; method: string | null } | null
  train_s: number | null
  ms_per_decision: { p50: number | null; p95: number | null } | null
  watts: { radio_only: number | null } | null
  bytes_out: number | null
  images_stored: number | null
  models_on_board: number | null
}

const sourceLabels = { live: 'LIVE', sim: 'FAKE', replay: 'REPLAY' }
const cameraLabels = { on: 'CAMERA ON', off: 'CAMERA OFF', stalled: 'CAMERA STALLED', unknown: 'CAMERA UNKNOWN' }
const alertLabels = { none: '', counting: 'Monitoring stillness', check_on: 'No-movement alert' }

function agreement(score: Score | null | undefined) {
  if (score?.correct == null || !score.total) return null
  return Math.round(100 * score.correct / score.total)
}

export function adaptHudState(state: ScreenState, proof: Proof | null, receivedAt = Date.now(), now = Date.now()) {
  const feedStatus = now - receivedAt > 1000 ? 'stale' : state.health.status
  return {
    feedStatus,
    source: sourceLabels[state.src],
    camera: cameraLabels[state.cam],
    movement: state.alert.state,
    alert: alertLabels[state.alert.state],
    alertLimit: state.alert.limit_s,
    alertZone: state.alert.state === 'none' ? null : state.alert.zone,
    checkin: state.alert.state === 'none' && state.checkin !== null,
    narration: state.narration,
    advice: state.advice,
    router: state.router,
    prediction: feedStatus === 'blind' || feedStatus === 'stale' ? null : state.pred,
    proof: {
      agreement: agreement(proof?.zone),
      personObjectScore: agreement(proof?.person_vs_object),
      trainSeconds: proof ? proof.train_s : state.model.train_s,
      decisionMs: proof ? proof.ms_per_decision?.p50 ?? null : state.model.ms_per_decision,
      watts: proof?.watts?.radio_only ?? null,
      bytesOut: proof?.bytes_out ?? null,
      images: proof?.images_stored ?? null,
      models: proof?.models_on_board ?? null,
    },
  }
}

export type HudState = ReturnType<typeof adaptHudState>
