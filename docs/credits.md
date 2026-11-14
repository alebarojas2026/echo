# Credits

Radio Sight was built at MadHacks 2026 for the Qualcomm / N+1 track, following the theme "Let's Dig In."

## Libraries

The repository does not yet contain third-party dependency manifests, so no software library names or versions are recorded here. As implementation dependencies land, this section should list every direct third-party library with its version, license, project link, and the Radio Sight module that uses it. The checked-in manifest in each module remains the source of truth.

| Library | Version | License | Used by | Project link |
|---|---|---|---|---|
| _Add from committed dependency manifests_ | _Add version_ | _Add license_ | _Add module_ | _Add link_ |

## Research

Radio Sight draws on radio tomographic imaging: using changes in received signal strength across multiple wireless links to estimate attenuation within an area.

Joey Wilson and Neal Patwari, ["Radio Tomographic Imaging with Wireless Networks"](https://span.ece.utah.edu/uploads/RTI_version_3.pdf), *IEEE Transactions on Mobile Computing*, vol. 9, no. 5, pp. 621–632, 2010.

The paper establishes the core idea of combining signal-strength changes from many links into a spatial estimate. Radio Sight applies that foundation to local dead-zone mapping, presence and movement sensing, and on-device room feedback.

## Platform

- Arduino UNO Q with Qualcomm Dragonwing for local processing
- Raspberry Pi 5 as the demo router

## Project

Radio Sight is released under the repository's MIT License. Contributions and dependencies retain their own copyright and license terms.
