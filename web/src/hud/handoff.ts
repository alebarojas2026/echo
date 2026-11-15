import type { StateMsg } from '../room/contract'

type Timing = { started_t?: number; radio_only_t?: number | null }
type Lesson = { started_t?: number; agree?: number; of?: number; fits?: number; fitting?: boolean }
const stamp = (value: unknown, end: number): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= end
export const runTime = (ms: number) => `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}`

/** Only this adapter knows the board's handoff timing shape. Missing timing stays missing. */
export function handoff(state: StateMsg | null, stale: boolean) {
  const unknown = { phase: 'unknown', title: 'CAMERA UNKNOWN', time: '', detail: 'Camera status unknown', teaching: 0, radio: 0, edge: false }
  if (!state || stale) return { ...unknown, detail: 'Waiting for live readings' }
  const cam = state.cam as string
  if (cam !== 'on' && cam !== 'off') return { ...unknown, title: cam === 'stalled' ? 'CAMERA STALLED' : unknown.title, detail: cam === 'stalled' ? 'Camera is not teaching' : unknown.detail }
  const timing = (state as StateMsg & { handoff?: Timing }).handoff
  const lesson = (state.model?.training as { lesson?: Lesson } | null)?.lesson
  const start = timing?.started_t ?? lesson?.started_t
  const off = timing?.radio_only_t
  const knownStart = stamp(start, state.t)
  const knownOff = cam === 'off' && stamp(off, state.t) && (!knownStart || off >= start)
  const total = knownStart ? state.t - start : 0
  const scale = Math.max(120000, total)
  const teaching = knownStart && (cam === 'on' || knownOff) ? ((knownOff ? off : state.t) - start) / scale : 0
  const radio = knownStart && knownOff ? (state.t - off) / scale : 0
  // A board that does not publish when the camera came out: RADIO ONLY with no duration, and the strip drawn whole.
  if (cam === 'off') return { phase: 'radio', title: 'RADIO ONLY', time: knownOff ? runTime(state.t - off) : '', detail: 'Camera unplugged', teaching, radio: knownStart && knownOff ? radio : 1, edge: knownStart && knownOff }
  const agreement = Number.isInteger(lesson?.agree) && Number.isInteger(lesson?.of) && lesson!.of! >= 3 && lesson!.agree! >= 0 && lesson!.agree! <= lesson!.of!
  const fits = Number.isInteger(lesson?.fits) && lesson!.fits! >= 0 ? `${lesson!.fits} fits` : ''
  const detail = [agreement ? `${lesson!.agree} of ${lesson!.of} agree` : '', fits, lesson?.fitting ? 'Fitting' : ''].filter(Boolean).join(' · ')
  return { phase: 'teaching', title: lesson ? 'CAMERA TEACHING' : 'CAMERA ON', time: knownStart ? runTime(total) : '', detail: detail || (lesson ? 'Learning from the camera' : 'Ready for a lesson'), teaching, radio: 0, edge: false }
}

/** The strip is on whenever there is a live reading; a replayed second has no camera of its own. */
export function handoffShown(state: StateMsg | null, stale: boolean): boolean {
  return !!state && !stale && state.src !== 'replay'
}
