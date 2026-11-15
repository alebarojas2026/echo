# Credits

Echo was built at MadHacks 2026 for the Qualcomm / N+1 track, following the theme "Let's Dig In."

## Libraries

The project currently uses these third-party packages. An entry marked `Not pinned in this repository` is imported by code on `main`, but its owning module has not declared a version yet.

| Library | Version | License | Role | Used by | Project link |
|---|---|---|---|---|---|
| pytest | Unpinned | MIT | Test | `brain/`, `bus/`, `sim/`, `narrator/` | [pytest](https://pytest.org/) |
| websockets | `>=12` in `narrator/`; `==17.1` in `scripts/`; unpinned in `brain/` | BSD-3-Clause | Runtime and demo check | `brain/`, `narrator/`, `scripts/` | [websockets](https://websockets.readthedocs.io/) |
| NumPy | Unpinned | BSD-3-Clause | Runtime and benchmark | `advisor/`, `board/`, `brain/` | [NumPy](https://numpy.org/) |
| scikit-learn | Unpinned | BSD-3-Clause | Runtime and benchmark | `board/`, `brain/` | [scikit-learn](https://scikit-learn.org/) |
| OpenCV (`cv2`) | Not pinned in this repository | Apache-2.0 | Runtime | `teacher/` | [OpenCV](https://opencv.org/) |
| jsonschema | `>=4.18` | MIT | Test and CI | `contracts/` | [jsonschema](https://python-jsonschema.readthedocs.io/) |
| referencing | Transitive, unpinned | MIT | Validation support | `contracts/` | [referencing](https://referencing.readthedocs.io/) |
| three | `^0.187.0` | MIT | Runtime | `web/` | [three.js](https://threejs.org/) |
| Vite | `^8.3.8` in `web/`; `8.3.8` in `web/tests/` | MIT | Build and development | `web/`, `web/tests/` | [Vite](https://vite.dev/) |
| Vitest | `^5.1.0` | MIT | Test | `web/` | [Vitest](https://vitest.dev/) |
| TypeScript | `^7.0.2` | Apache-2.0 | Type checking | `web/` | [TypeScript](https://www.typescriptlang.org/) |
| `@types/three` | `^0.187.0` | MIT | Development types | `web/` | [DefinitelyTyped](https://github.com/DefinitelyTyped/DefinitelyTyped) |
| `@playwright/test` | `1.60.0` | Apache-2.0 | Browser test | `web/tests/` | [Playwright](https://playwright.dev/) |
| `@gltf-transform/core` | `^4.5.1` | MIT | 3D asset preparation | `web/` | [glTF Transform](https://gltf-transform.dev/) |
| `@gltf-transform/extensions` | `^4.5.1` | MIT | 3D asset preparation | `web/` | [glTF Transform](https://gltf-transform.dev/) |
| `@gltf-transform/functions` | `^4.5.1` | MIT | 3D asset preparation | `web/` | [glTF Transform](https://gltf-transform.dev/) |
| meshoptimizer | `^1.3.0` | MIT | 3D asset preparation | `web/` | [meshoptimizer](https://github.com/zeux/meshoptimizer) |
| Arduino App Bricks | Not pinned in this repository | MPL-2.0 | Runtime | `teacher/applab/` | [app-bricks-py](https://github.com/arduino/app-bricks-py) |

As implementation dependencies land, this table should list every direct third-party library with its declared version, license, project link, and the Echo module that uses it. The checked-in manifest in each module remains the source of truth.

## Typefaces

The screens use two typefaces. Both files are served from the board itself, in `web/src/hud/fonts/`, each beside its licence text; no page asks an outside host for a font.

| Typeface | Weights | License | Role | Used by | Project link |
|---|---|---|---|---|---|
| Poppins | 400, 500, 600 | SIL Open Font License 1.1 | All text | `web/` | [Poppins](https://fonts.google.com/specimen/Poppins) |
| Tenor Sans | 400 | SIL Open Font License 1.1 | Titles | `web/` | [Tenor Sans](https://fonts.google.com/specimen/Tenor+Sans) |

## Research

Echo is built on the physics behind radio tomographic imaging, on a single link: a body in the path of a wireless link weakens the received signal.

Joey Wilson and Neal Patwari, ["Radio Tomographic Imaging with Wireless Networks"](https://span.ece.utah.edu/uploads/RTI_version_3.pdf), *IEEE Transactions on Mobile Computing*, vol. 9, no. 5, pp. 621–632, 2010.

The paper establishes the core idea of combining signal-strength changes from many links into a spatial estimate. Echo uses the simplest case of that idea: one Wi-Fi line across one spot, for presence and still or moving, decided on the device.

## Platform

- Arduino UNO Q with Qualcomm Dragonwing for local processing
- Two Raspberry Pi 5 boards: one makes the Wi-Fi signal, the other measures it, and each signs the record

## Project

Echo is released under the repository's MIT License. Contributions and dependencies retain their own copyright and license terms.
