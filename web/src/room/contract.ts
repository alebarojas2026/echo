// Message shapes from CONTRACTS.md v2, sections 1 and 5. The panels in web/src/hud can import these too.

export type Src = 'live' | 'sim' | 'replay'

export interface Envelope {
  v: 2
  type: string
  t: number
  seq: number
  src: Src
  recv_t?: number
}

export interface LinkState {
  id: string
  dbm: number | null
  base_dbm: number | null
  drop_db: number | null
  rate_hz: number | null
  expected_hz: number | null
  status: string // ok | stale | blind
  why: number | null
}

export interface Health {
  status: 'ok' | 'degraded' | 'blind'
  blind: string[]
  reason: 'rate' | 'jump' | null
}

export interface Pred {
  present: boolean
  kind: 'person' | 'object' | 'none'
  zone: number
  zone_set: number[]
  probs: number[] // [empty, z1, z2, z3, z4]
  motion: 'moving' | 'still'
  still_s: number
  why: string[]
}

export interface ObjectMark {
  xy_m: [number, number]
  near: string
  since_s: number
  drop_db: number
}

export interface Xray {
  w: number
  h: number
  cell_m: number
  origin_m: [number, number]
  moving_db: number[]
  static_db: number[]
  n_links: number
}

export interface Alert {
  state: 'none' | 'counting' | 'check_on'
  zone: number | null
  still_s: number | null
  limit_s: number | null
}

export interface Checkin {
  t: number
  link: string
}

export interface Advice {
  id: string
  cause: string
  near: string
  xy_m: [number, number]
  link: string
  to_spot: string
  move_m: [number, number]
  dist_change_m: number | null
  text: string
  before_dbm: number | null
  after_dbm: number | null
  why: string[]
}

export interface Narration {
  text: string
  event_id: string
  t: number
  source: 'llm' | 'template'
  gen_ms: number | null
}

export interface Teacher {
  present: boolean
  zone: number
  motion: 'moving' | 'still'
}

export interface Model {
  trained: boolean
  ver: string | null
  train_s: number | null
  ms_per_decision: number | null
  windows: number | null
  train_sessions: string[]
  training: unknown
}

export interface Board {
  cpu_temp_c: number | null
  cpu_mhz: number | null
  cpu_pct: number | null
}

export interface StateMsg extends Envelope {
  type: 'state'
  cam: 'on' | 'off' | 'stalled'
  router: string
  links: LinkState[]
  health: Health
  pred: Pred | null
  objects: ObjectMark[]
  xray: Xray | null
  alert: Alert | null
  checkin: Checkin | null
  advice: Advice | null
  narration: Narration | null
  teacher: Teacher | null
  model: Model | null
  board: Board | null
}

export interface EventMsg extends Envelope {
  type: 'event'
  id: string
  kind: string
  info: Record<string, unknown>
}

export type CmdName =
  | 'train'
  | 'baseline'
  | 'reset_alert'
  | 'record_start'
  | 'record_stop'
  | 'label_mode'
  | 'router_moved'
  | 'router_home'
  | 'relearn'
  | 'truth'

export interface CmdMsg {
  v: 2
  type: 'cmd'
  cmd: CmdName
  args: Record<string, unknown>
}
