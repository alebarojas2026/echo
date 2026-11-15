import type { StateMsg } from '../room/contract'

type Training = { started_t?: number; lesson?: { started_t?: number; agree?: number; of?: number; fits?: number; fitting?: boolean } }
const seconds = (end: number, start: unknown) => typeof start === 'number' && Number.isFinite(start) && end >= start ? Math.floor((end - start) / 1000) : null
export class LessonProgress {
  private start: number | undefined
  private completed: { line: string; until: number } | undefined
  update(state: StateMsg | null, stale: boolean, now = performance.now()) {
    if (!state || stale) return null
    const training = state.model?.training as Training | null
    const lesson = training?.lesson
    if (training) {
      this.completed = undefined
      if (lesson) this.start = lesson.started_t
      const elapsed = seconds(state.t, lesson?.started_t ?? training.started_t)
      const of = lesson?.of, agree = lesson?.agree
      const measured = typeof of === 'number' && Number.isInteger(of) && of >= 3 && typeof agree === 'number' && Number.isInteger(agree) && agree >= 0 && agree <= of
      return { line: `${lesson ? 'Teaching the radio' : 'Training'} · ${elapsed ?? '__'} s`,
        agreement: measured ? `Radio agrees with the camera: ${agree} of ${of}` : '', ratio: measured ? agree / of : null }
    }
    if (this.start !== undefined) {
      const elapsed = seconds(state.t, this.start)
      this.completed = state.model?.trained && elapsed !== null ? { line: `Taught in ${elapsed} s`, until: now + 4000 } : undefined
      this.start = undefined
    }
    return this.completed && now < this.completed.until ? { line: this.completed.line, agreement: '', ratio: null } : null
  }
}
