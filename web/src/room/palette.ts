// The room's colours: a dark instrument look in which each colour means one thing.
export const BG = 0x111316 // page and canvas
export const FLOOR = 0x1a1d21 // floor and walls
export const WALL_SHADE = 0x0d0f11 // scanned walls darken toward this by which way they face
export const EDGE = 0x353b43 // room edges, posts, zone lines
export const SQUARE = 0x6b7480 // the sensing square's outline
export const TEXT = 0xe6e8eb // node cubes, the current router spot
export const LINK = 0x858e99 // a healthy radio link: neutral, so only the links that matter take a colour
export const PERSON = 0x1fa5cf // people: shadow, ghost, the links that explain where they are
export const PERSON_HOT = 0xa6e0f2 // the hottest part of a person's shadow: the same blue, lighter
export const OBJECT = 0xa9b4c2 // objects: hatching and markers
export const ACTION = 0x34b277 // something to do: the router advice arrow, the check-in
export const FAULT = 0xf2555a // a broken link
