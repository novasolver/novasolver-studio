# NovaSolver Studio — deployment notes for IT departments

This page lists everything Studio sends over the network and where it keeps data, so that it can be approved for
use in a company. It describes version 0.7.

## Network access

Studio makes exactly two kinds of outgoing requests. Both are HTTPS GET requests that send nothing about the user,
the computer or the models. The only header is `User-Agent: NovaSolverStudio/<version>`.

| What | When | Address | Can be turned off |
|---|---|---|---|
| Update check | once a day at start-up, and when the user presses "Check for updates" | `https://novasolver.jp/studio/latest.json`, then `https://raw.githubusercontent.com/novasolver/novasolver-studio/main/latest.json` | yes: Help → "Check once a day", or offline mode |
| Update download | only when the user presses "Update now" | `https://github.com/novasolver/novasolver-studio/releases/download/...` or `https://novasolver.jp/dl/studio/...` | yes: offline mode |
| Solved examples | only when the user opens the examples list | `https://github.com/novasolver/novasolver-studio/releases/download/v<version>/`, or the same files at `https://novasolver.jp/dl/studio/examples/v<version>/` when GitHub cannot be reached (`examples.json` and `example-*.nscase`, checked by SHA-256) | yes: offline mode (examples already downloaded stay available) |

The update notice is signed (Ed25519). Studio refuses a notice whose signature does not match the key built into
it, downloads only from the two hosts above, and checks the SHA-256 of the download before installing it.

Links in the Help dialog (site, GitHub, community) open the user's browser; Studio itself does not load them.

There is no telemetry, no crash reporting, no account and no licence server.

## Offline mode

Studio does not connect to the internet at all when any of these is true:

- the environment variable `NOVASTUDIO_OFFLINE=1` is set;
- an empty file named `offline` is next to `NovaSolverStudio.exe` (deploy it together with the zip);
- an empty file named `offline` is in the data folder (`%LOCALAPPDATA%\NovaSolverStudio`).

The Help dialog then says "Offline mode" and offers no update. To update, replace the folder with a new release zip.

## Local server

The interface is a web page served by Studio itself on `http://127.0.0.1:8765` (the next free port if it is taken).
It listens on the loopback address only and is not reachable from other computers.

## Where data is kept

| Data | Location |
|---|---|
| Cases (models, meshes, results) | `Documents\NovaSolverStudio\workspace` (can be changed with `NOVASTUDIO_WORKSPACE`) |
| Settings, update state, example cache, solver queue | `%LOCALAPPDATA%\NovaSolverStudio` |
| OpenFOAM (installed on first use of flow analysis, with the user's consent) | `%LOCALAPPDATA%\NovaSolverStudio\solvers` |

Nothing is written outside these folders and the app folder. Uninstalling is deleting the three folders.

## Bundled software and licences

| Component | Licence |
|---|---|
| NovaSolver Studio | see `LICENSE` |
| CalculiX 2.23 (structural solver, run as a separate program) | GPL v2 |
| Gmsh (mesher, Python package) | GPL v2 or later |
| OpenFOAM v2606 (flow solver, downloaded on first use, run as a separate program) | GPL v3 |
| Python, NumPy, SciPy, PyAMG, FastAPI and others | see `THIRD_PARTY_NOTICES.md` |

The solvers run as separate processes on the user's computer; models are never sent anywhere.

## Code signing

The release zip is not yet signed with an Authenticode certificate, so Windows SmartScreen may warn on first start.
Every release publishes the SHA-256 of the zip next to it on GitHub and novasolver.jp for verification.
