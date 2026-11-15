type CommandName = 'train' | 'baseline' | 'record_start' | 'record_stop' | 'label_mode'
  | 'router_moved' | 'router_home' | 'reset_alert' | 'reset'

export type HudCommand = { v: 2; type: 'cmd'; cmd: CommandName; args: Record<string, string | boolean> }

export function mountHudControls(root: HTMLElement, send: (command: HudCommand) => void) {
  root.innerHTML = `
    <section class="hud-card">
      <h2>Controls</h2>
      <form>
        <fieldset>
          <legend>Recording</legend>
          <label>Session <input name="session" required></label>
          <label>Purpose <select name="purpose"><option>demo</option><option>train</option>
            <option>heldout</option><option>object</option><option>crowd</option></select></label>
          <label>Walker <input name="walker" required></label>
          <button>Start recording</button>
          <button type="button" data-command="record_stop">Stop recording</button>
        </fieldset>
      </form>
      <fieldset>
        <legend>Setup</legend>
        <button type="button" data-testid="train-button" data-command="train">Train</button>
        <button type="button" data-command="baseline" data-keep-model="true">New baseline, keep the model</button>
        <button type="button" data-command="baseline">New place: baseline and forget the model</button>
        <label for="hud-label-mode">Label mode</label><select id="hud-label-mode" name="mode"><option>off</option><option>person</option><option>object</option></select>
        <button type="button" data-command="label_mode">Set label mode</button>
      </fieldset>
      <fieldset>
        <legend>Router and alert</legend>
        <label>New router spot <select name="spot"><option>S-W30</option><option>S-E30</option></select></label>
        <button type="button" data-command="router_moved">Router moved</button>
        <button type="button" data-command="router_home">Router home</button>
        <button type="button" data-command="reset_alert">Reset alert</button>
        <button type="button" data-command="reset">Reset demo</button>
      </fieldset>
    </section>
  `
  const emit = (cmd: CommandName, args: Record<string, string | boolean> = {}) => send({ v: 2, type: 'cmd', cmd, args })
  const form = root.querySelector('form')!
  form.addEventListener('submit', event => {
    event.preventDefault()
    const data = new FormData(form)
    const session = String(data.get('session')).trim()
    const walker = String(data.get('walker')).trim()
    if (session && walker) emit('record_start', { session, walker, purpose: String(data.get('purpose')) })
  })
  root.querySelectorAll<HTMLButtonElement>('button[data-command]').forEach(button => {
    button.addEventListener('click', () => {
      const cmd = button.dataset.command as CommandName
      if (cmd === 'baseline') {
        if (button.dataset.keepModel === 'true') emit(cmd, { keep_model: true })
        else if (window.confirm('Start a baseline for a new place? This forgets the current model and stops using the older recordings for training. This cannot be undone.')) emit(cmd)
      }
      else if (cmd === 'label_mode') emit(cmd, { mode: root.querySelector<HTMLSelectElement>('[name="mode"]')!.value })
      else if (cmd === 'router_moved') emit(cmd, { spot: root.querySelector<HTMLSelectElement>('[name="spot"]')!.value })
      else emit(cmd)
    })
  })
}
