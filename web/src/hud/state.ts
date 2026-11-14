export type HudState = {
  source: 'LIVE' | 'FAKE' | 'REPLAY'
  camera: 'off' | 'on'
  movement: 'no-movement' | 'check-in' | 'normal'
  narration: string
  signal: { before: number | null; after: number | null }
  proof: {
    agreement: number | null
    trainSeconds: number | null
    decisionMs: number | null
    watts: number | null
    bytesOut: number | null
    images: number | null
  }
}

export function readHudState(params = new URLSearchParams(window.location.search)): HudState {
  const source = params.get('source')
  const checkedIn = params.get('movement') === 'check-in'

  return {
    source: source === 'LIVE' || source === 'REPLAY' ? source : 'FAKE',
    camera: 'off',
    movement: checkedIn ? 'check-in' : 'no-movement',
    narration: checkedIn
      ? 'The room occupant checked in.'
      : 'The radio detects someone in the room who has stopped moving.',
    signal: { before: null, after: null },
    proof: {
      agreement: null,
      trainSeconds: null,
      decisionMs: null,
      watts: null,
      bytesOut: 0,
      images: 0,
    },
  }
}
