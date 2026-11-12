# NovaSolver Studio for Claude Code

This plugin connects Claude Code to the published local Studio MCP server. It includes a `/novasolver-studio:simulate` workflow skill. Requires Python 3.10+ and `uv` on PATH.

## Install from GitHub

Run in your terminal:

```sh
claude plugin marketplace add https://github.com/novasolver/novasolver-studio.git
claude plugin install novasolver-studio@novasolver
```

Start a new Claude Code session, inspect `/mcp`, then ask it to create and solve a coarse cantilever example. This is NovaSolver's own GitHub marketplace, not a listing in Anthropic's official directory. Installation changes your Claude plugin settings; Studio case files stay in its local workspace.

## Local preview

From a checkout containing this plugin:

```sh
claude --plugin-dir ./plugins/novasolver-studio
```

In Claude Code, inspect `/mcp`, then try:

> Create a coarse cantilever example, solve it, and report the result and reference-check status.

The server package is pinned to `novasolver-studio==0.7.6.post1`. Plugin 0.1.1 starts it with `uv run --locked` using the bundled project and `uv.lock`, which records package sources, versions and artifact hashes. The first launch downloads the locked packages from PyPI and creates a local virtual environment in the plugin folder; that folder must be writable. Simulation files use Studio's standard workspace; `NOVASTUDIO_WORKSPACE` can select an isolated test workspace before launching Claude.

## Marketplace preview

From the repository checkout:

```sh
claude plugin marketplace add .
claude plugin install novasolver-studio@novasolver
```

These commands change Claude's plugin settings. They are optional; use `--plugin-dir` to preview without persistent installation.

## Scope and verification

The published server has 35 tools. Genesis is not available in this package. Studio executes locally, but tool responses and requested images are sent to the AI provider used by Claude Code. No personal account identifier or credential is bundled with this plugin.

Validation status and actual Claude Code integration testing are recorded separately; manifest validation is not proof of an end-to-end simulation.

### Verified 2026-11-12

Windows / Python 3.12 / Claude Code CLI (Haiku): both manifests pass `claude plugin validate`; exact plugin uvx command exposes 35 MCP tools and solves a coarse cantilever. Claude Code loaded this plugin with `--plugin-dir`, called environment_check, list_templates, create_case, run_simulation, job_status and get_results, and reported reference validation separately from the untested mesh-convergence study. No permission denials.

This Claude test used an isolated workspace and process-local PATH containing uvx.

Additional direct MCP tests (the same pinned server, not additional Claude-client tests) imported the bundled `l_bracket.step`, generated a real tet10 mesh, and ran coarse/normal/fine built-in FEM studies. Two fresh runs reproduced the results:

| Case | Numerical convergence | Displacement mesh study | Remaining limitation |
| --- | --- | --- | --- |
| Cantilever | Passed at all three levels | Passed; GCI 0.403% (5% limit) | Peak stress at the fixed support is not a strength assessment |
| L-bracket, 100 N in +X | Passed at all three levels | Failed; GCI 7.784% (5% limit) | More mesh/geometry assessment is needed; stress-singularity warning |

The bracket study correctly remains unverified. A completed calculation is not sufficient evidence of mesh independence. Neither displacement study establishes peak-stress convergence or real-world safety.

After publication, GitHub marketplace retrieval and installation were verified in a fresh, isolated Claude configuration on Windows. Other operating systems' plugin installation remains untested. CalculiX and OpenFOAM were unavailable in the plugin test environment, so no external-solver plugin result is claimed. Genesis is not in the pinned release.

Plugin 0.1.1's locked-project launcher was additionally tested through direct MCP and actual Claude Code (Haiku): 35 tools, a new coarse cantilever solve, and its reference check passed, with no permission denials. This launcher test did not rerun the mesh study.
