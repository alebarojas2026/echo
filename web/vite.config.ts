/// <reference types="vitest/config" />
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

function boardFiles(): Plugin {
  return {
    name: 'board-files',
    configureServer: (server) => void server.middlewares.use(boardJson),
    configurePreviewServer: (server) => void server.middlewares.use(boardJson),
  }
}

export default defineConfig({
  plugins: [boardFiles()],
  build: { chunkSizeWarningLimit: 700 }, // three.js is most of the bundle; the board serves it locally
  // web/tests (Playwright) and web/src/game (node:test) have their own runners.
  test: { include: ['src/room/**/*.test.ts'] },
})
