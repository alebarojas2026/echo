# Credits

Radio Sight was built at MadHacks 2026 for the Qualcomm / N+1 track, following the theme "Let's Dig In."

## Libraries

The committed dependency manifests currently declare one third-party package:

| Library | Version | License | Used by | Project link |
|---|---|---|---|---|
| pytest | Unpinned | MIT | `bus/`, `sim/` | [pytest](https://pytest.org/) |

`pytest` is development and test tooling. No third-party runtime library is currently declared in a committed manifest.

As implementation dependencies land, this table should list every direct third-party library with its declared version, license, project link, and the Radio Sight module that uses it. The checked-in manifest in each module remains the source of truth.

## Research

Radio Sight draws on radio tomographic imaging: using changes in received signal strength across multiple wireless links to estimate attenuation within an area.

Joey Wilson and Neal Patwari, ["Radio Tomographic Imaging with Wireless Networks"](https://span.ece.utah.edu/uploads/RTI_version_3.pdf), *IEEE Transactions on Mobile Computing*, vol. 9, no. 5, pp. 621–632, 2010.

The paper establishes the core idea of combining signal-strength changes from many links into a spatial estimate. Radio Sight applies that foundation to local dead-zone mapping, presence and movement sensing, and on-device room feedback.

## Platform

- Arduino UNO Q with Qualcomm Dragonwing for local processing
- Raspberry Pi 5 as the demo router

## Project

Radio Sight is released under the repository's MIT License. Contributions and dependencies retain their own copyright and license terms.
