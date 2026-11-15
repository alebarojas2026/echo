// npm run scan:desks -- <hall.json> [out.json]
// Writes the hall model's desks (web/public/models/hall-desks.json by default) from the hall builder's hall.json,
// so the desk layout can stand at a real desk and align mode can step from desk to desk (web/src/room/desks.ts).
// The file stays out of git with the model it describes.
//
// hall.json is in the builder's plan frame (X along the front wall, Y into the hall); the model stores x = -X,
// z = Y. A desk point is centre + r * (sin th, cos th) in both, with th mirrored.
import { readFileSync, writeFileSync } from 'node:fs'

const [src, out = new URL('../../../public/models/hall-desks.json', import.meta.url)] = process.argv.slice(2)
if (!src) {
  console.error('usage: npm run scan:desks -- <hall.json> [out.json]')
  process.exit(1)
}
const hall = JSON.parse(readFileSync(src, 'utf8'))
const desks = hall.desks.map((d) => ({
  row: d.row,
  wedge: d.wedge,
  r_m: +d.r.toFixed(3),
  th0_deg: +(-d.th1).toFixed(3),
  th1_deg: +(-d.th0).toFixed(3),
  floor_m: +d.floor.toFixed(3),
}))
// Blocks are numbered from the layout's west (the audience's left as they face the front).
const order = [...new Set(desks.map((d) => d.wedge))].sort((a, b) => {
  const mid = (w) => desks.filter((d) => d.wedge === w).reduce((s, d) => s + d.th0_deg + d.th1_deg, 0)
  return mid(a) - mid(b)
})
for (const d of desks) d.wedge = order.indexOf(d.wedge)
const file = { centre_m: [+(-hall.centre[0]).toFixed(4), +hall.centre[1].toFixed(4)], desk_depth_m: +hall.desk_depth.toFixed(3), desks }
writeFileSync(out, `${JSON.stringify(file)}\n`)
console.log(`${desks.length} desks in ${new Set(desks.map((d) => d.row)).size} rows written`)
