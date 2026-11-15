// The desk layout from the contract PR (#415): radio/nodes.json's layout fields, for tests that must pass on both
// the square (today's file) and the desk, whichever radio/nodes.json the repo has.
export const DESK_LAYOUT = {
  v: 2,
  layout: 'desk',
  frame: { units: 'm', size_m: [1.6, 1.1], strip_m: [1.6, 0.6], zone_split_x_m: 0.8 },
  nodes: [
    { id: 'unoq', name: 'Board', xyz_m: [1.1, 0.6, 1.0], roles: ['receiver'] },
    { id: 'pi5', name: 'Pi A', xyz_m: [0.8, 1.1, 1.0], roles: ['router', 'beacon', 'receiver'] },
    { id: 'pi5b', name: 'Pi B', xyz_m: [0.5, 0.6, 1.0], roles: ['beacon', 'receiver'] },
    { id: 'east', name: 'East beacon', xyz_m: [1.6, 0.25, 1.0], roles: ['beacon'] },
    { id: 'west', name: 'West beacon', xyz_m: [0.0, 0.25, 1.0], roles: ['beacon'] },
  ],
  links: [
    'pi5>unoq:wifi', 'pi5>unoq:ble', 'east>unoq:ble', 'west>unoq:ble', 'east>pi5:ble', 'west>pi5:ble',
    'pi5b>unoq:ble', 'pi5>pi5b:wifi', 'pi5>pi5b:ble', 'east>pi5b:ble', 'west>pi5b:ble', 'pi5b>pi5:ble',
  ].map((id) => {
    const [, tx, rx, kind] = /^(\w+)>(\w+):(\w+)$/.exec(id)!
    return { id, tx, rx, kind, expected_hz: null }
  }),
  zones: [
    { id: 1, side: 'W', name: 'Left', centre_m: [0.4, 0.3], still_alert_s: 10 },
    { id: 2, side: 'E', name: 'Right', centre_m: [1.2, 0.3], still_alert_s: 10 },
  ],
  router_spots: [
    { id: 'S-home', xyz_m: [0.8, 1.1, 1.0] },
    { id: 'S-W30', xyz_m: [0.5, 1.1, 1.0] },
    { id: 'S-E30', xyz_m: [1.1, 1.1, 1.0] },
  ],
  tray_spots: [{ id: 'T1', xyz_m: [0.86, 1.0, 1.0] }],
  hall: {
    beacons: [
      { node: 'h', id: 'H', data_hex: 'FFFF525348', xyz_m: null as number[] | null },
      { node: 'j', id: 'J', data_hex: 'FFFF52534A', xyz_m: null as number[] | null },
    ],
  },
}
