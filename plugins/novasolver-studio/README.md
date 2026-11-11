# NovaSolver Studio for Claude Code

This development plugin connects Claude Code to the published local Studio MCP server. It includes a `/novasolver-studio:simulate` workflow skill. Requires Python 3.10+ and `uvx` on PATH (installed with uv).

## Local preview

From a checkout containing this plugin:

```sh
claude --plugin-dir ./plugins/novasolver-studio
```

In Claude Code, inspect `/mcp`, then try:

> Create a coarse cantilever example, solve it, and report the result and reference-check status.

The server package is pinned to `novasolver-studio==0.7.6.post1`. The first launch downloads the package and dependencies from PyPI. Simulation files use Studio's standard workspace; `NOVASTUDIO_WORKSPACE` can select an isolated test workspace before launching Claude.

## Marketplace preview

From the repository checkout:

```sh
claude plugin marketplace add .
claude plugin install novasolver-studio@novasolver
```

These commands change Claude's plugin settings. They are optional; use `--plugin-dir` to preview without persistent installation. Repository-wide GitHub installation is not advertised until the marketplace is merged to the default branch and tested.

## Scope and verification

The published server has 35 tools. Genesis is not available in this package. Studio executes locally, but tool responses and requested images are sent to the AI provider used by Claude Code. No personal account identifier or credential is bundled with this plugin.

Validation status and actual Claude Code integration testing are recorded separately; manifest validation is not proof of an end-to-end simulation.

### Verified 2026-11-12

Windows / Python 3.12 / Claude Code CLI (Haiku): both manifests pass `claude plugin validate`; exact plugin uvx command exposes 35 MCP tools and solves a coarse cantilever. Claude Code loaded this plugin with `--plugin-dir`, called environment_check, list_templates, create_case, run_simulation, job_status and get_results, and reported reference validation separately from the untested mesh-convergence study. No permission denials.

This test used an isolated workspace and process-local PATH containing uvx. Persistent marketplace installation, CAD import, mesh convergence, other operating systems and Genesis were not tested. Genesis is not in the pinned release.
