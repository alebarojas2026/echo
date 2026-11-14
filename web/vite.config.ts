/// <reference types="vitest/config" />
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { defineConfig, type Plugin } from 'vite'

// `vite` and `vite preview` answer /nodes.json and /proof.json from the repo the way board/serve.py does on
// the board, so the screen and its tests read the same files in development as on the kiosk.

const NODES = new URL('../radio/nodes.json', import.meta.url)
const PROOF = new URL('../proof/proof.json', import.meta.url)

// CONTRACTS.md section 7 with nothing measured yet: what serve.py sends until proof/proof.json exists.
export const EMPTY_PROOF = {
  zone: { correct: null, total: null, ci95: null, sessions: null, walkers: null, method: null },
  threshold_zone: { correct: null, total: null },
  person_vs_object: { correct: null, total: null, tray_placements: null },
  false_alarms_per_min: null,
  train_s: null,
  ms_per_decision: { p50: null, p95: null },
  watts: { idle: null, teaching: null, radio_only: null, source: null },
  bytes_out: null,
  images_stored: null,
  models_on_board: null,
  measured_at: null,
  commit: null,
}

async function boardJson(req: IncomingMessage, res: ServerResponse, next: () => void) {
  const path = (req.url ?? '').split('?')[0]
  if (path !== '/nodes.json' && path !== '/proof.json') return next()
  let body: string | Buffer
  try {
    body = await readFile(path === '/nodes.json' ? NODES : PROOF)
  } catch {
    if (path === '/nodes.json') {
      res.statusCode = 404
      res.end()
      return
    }
    body = JSON.stringify(EMPTY_PROOF)
  }
  res.setHeader('content-type', 'application/json')
  res.setHeader('cache-control', 'no-store')
  res.end(body)
}

const ROOM_JSON = new URL('./public/models/room.json', import.meta.url)

// The room scan is optional: only a build that finds web/public/models/room.glb asks for it, so the kiosk
// never logs a 404 for a missing file. Its alignment, if any, is web/public/models/room.json.
function roomScan() {
  if (!existsSync(new URL('./public/models/room.glb', import.meta.url))) return null
  let fit = {}
  try {
    fit = JSON.parse(readFileSync(ROOM_JSON, 'utf8'))
  } catch {
    // no alignment file: the scan is centred on the square
  }
  return { url: 'models/room.glb', fit }
}

/** Only the four alignment numbers, each finite and in a sane range, or null. */
export function cleanFit(body: unknown): Record<string, unknown> | null {
  if (!body || typeof body !== 'object') return null
  const { offset_m, yaw_deg, scale, cut_m } = body as Record<string, unknown>
  const num = (v: unknown, lo: number, hi: number) => typeof v === 'number' && Number.isFinite(v) && v >= lo && v <= hi
  if (!Array.isArray(offset_m) || offset_m.length !== 2 || !offset_m.every((v) => num(v, -100, 100))) return null
  if (!num(yaw_deg, -360, 360) || !num(scale, 0.25, 4) || !num(cut_m, 0, 20)) return null
  return { offset_m, yaw_deg, scale, cut_m }
}

// Under `vite` only: the screen asks here for the scan on every load (GET), so a new room.glb or room.json
// shows on reload without a restart, and align mode's S saves room.json here (POST).
function roomScanApi(req: IncomingMessage, res: ServerResponse, next: () => void) {
  if (req.url?.split('?')[0] !== '/__room-scan') return next()
  res.setHeader('content-type', 'application/json')
  res.setHeader('cache-control', 'no-store')
  if (req.method !== 'POST') return void res.end(JSON.stringify(roomScan()))
  let body = ''
  req.on('data', (chunk: Buffer) => {
    body += chunk
    if (body.length > 4096) req.destroy()
  })
  req.on('end', () => {
    let fit = null
    try {
      fit = cleanFit(JSON.parse(body))
    } catch {
      // not JSON
    }
    if (!fit) {
      res.statusCode = 400
      return void res.end(JSON.stringify({ error: 'expected offset_m, yaw_deg, scale and cut_m' }))
    }
    writeFileSync(ROOM_JSON, `${JSON.stringify(fit, null, 2)}\n`)
    res.end(JSON.stringify({ saved: 'web/public/models/room.json' }))
  })
}

function boardFiles(): Plugin {
  return {
    name: 'board-files',
    configureServer: (server) => {
      server.middlewares.use(roomScanApi)
      server.middlewares.use(boardJson)
    },
    configurePreviewServer: (server) => void server.middlewares.use(boardJson),
  }
}

// Pages the board serves besides the screen, each at its own path: http://<board>:8080/game/ and /phone/.
// A page is built only once its file exists, so the phone page joins the build when it lands.
const PAGES: Record<string, string> = {
  game: 'src/game/index.html',
  phone: 'src/game/phone/index.html',
}
const pages = Object.entries(PAGES).filter(([, file]) => existsSync(new URL(file, import.meta.url)))

/** Writes each extra page to dist/<name>/index.html instead of dist/src/.../index.html. */
function pagePaths(): Plugin {
  return {
    name: 'page-paths',
    enforce: 'post',
    generateBundle(_, bundle) {
      for (const [name, file] of pages) {
        const page = bundle[file]
        if (!page || page.type !== 'asset') continue
        delete bundle[file]
        this.emitFile({ type: 'asset', fileName: `${name}/index.html`, source: page.source })
      }
    },
  }
}

export default defineConfig({
  plugins: [boardFiles(), pagePaths()],
  define: { __ROOM_SCAN__: JSON.stringify(roomScan()) },
  build: {
    chunkSizeWarningLimit: 700, // three.js is most of the bundle; the board serves it locally
    rolldownOptions: { input: { main: 'index.html', ...Object.fromEntries(pages) } },
  },
  // web/tests (Playwright) and web/src/game (node:test) have their own runners.
  test: { include: ['src/room/**/*.test.ts'] },
})
