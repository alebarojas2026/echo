import type { Proof, ScreenState } from './state'

export function mockFeed(params: URLSearchParams) {
  const source = params.get('source')
  const camera = params.get('cam')
  const movement = params.get('movement')
  const checkedIn = movement === 'check-in'
  const t = Date.now()
  const state: ScreenState = {
    v: 2, type: 'state', t, seq: 0,
    src: source === 'live' || source === 'replay' ? source : 'sim',
    links: source === 'live' ? [{ rate_hz: 1 }] : [],
    cam: camera === 'on' || camera === 'stalled' ? camera : 'off',
    router: 'S-home',
    health: { status: params.has('blind') ? 'blind' : 'ok' },
    pred: null,
    alert: {
      state: checkedIn ? 'none' : movement === 'counting' ? 'counting' : 'check_on',
      zone: null, still_s: null, limit_s: null,
    },
    checkin: checkedIn ? { t, link: 'pi5>unoq:wifi' } : null,
    advice: params.has('no-advice') ? null : {
      text: 'An obstruction is blocking the link. Move the router 30 cm west.',
      before_dbm: null,
      after_dbm: null,
    },
    narration: {
      text: checkedIn ? 'The room occupant checked in.' : 'The room occupant has stopped moving.',
      source: 'template',
    },
    model: { train_s: null, ms_per_decision: null },
  }
  const proof: Proof = {
    zone: { correct: null, total: null },
    person_vs_object: { correct: null, total: null },
    train_s: null,
    ms_per_decision: { p50: null, p95: null },
    watts: { radio_only: null },
    bytes_out: null,
    images_stored: null,
    models_on_board: null,
  }
  return { state, proof }
}
