---
name: simulate
description: Import CAD or create a NovaSolver Studio case, set engineering conditions, solve, and explain convergence and reference checks. Use for local FEM, thermal or CFD analysis through the Studio MCP server.
---

Use the connected NovaSolver Studio MCP tools. Respond in the user's language; pass `language` as `ja`, `en`, or `zh` where supported.

1. Call `environment_check` and inspect available tools. This plugin pins the published 0.7.6.post1 package. Do not promise Genesis or topology optimization: they are not in this release.
2. For an existing case, call `describe_case`. Otherwise use `list_templates` / `create_case`, or `import_geometry` with the user's file and intended physics. Resolve material, units, supports and loads from the user's request; ask about missing conditions that materially change the result. Never silently invent them.
3. Inspect face identifiers before assigning conditions. Use `render_view` with `quantity="faces"`, or `get_gui_selection` when the user selected faces. Apply `update_case` with the current `expected_revision`; refresh the description after a conflict rather than overwriting newer edits. Use `clone_case` for comparisons that should preserve the original.
4. Call `validate_case`, then `run_simulation`. Use the installed solver and supported mode; do not represent a preview as a final external-solver run. Poll `job_status` until completion, failure or the agreed budget. Stop after a failed attempt to diagnose the reported cause; do not repeatedly rerun unchanged inputs.
5. Read `get_results`; use `check_convergence` for mesh sensitivity and `verify_case` for supported reference comparisons when appropriate to the requested analysis. These may start additional work: explain scope and respect the user's computation limits. A completed solver run alone is not a verified design.
6. Report the assumptions, units, main numerical result, warnings, and separate statuses for solver completion, numerical convergence, mesh convergence and reference verification. Preserve failures and unsupported checks. A reference match does not validate the user's boundary conditions, material choice, fabrication or real-world safety.

Prefer `render_view`, `probe_results`, `compare_runs` and `export_results` for evidence. Do not upload geometry to another service. Although Studio runs locally, tool outputs included in the conversation reach the configured AI provider; use the user's confidentiality preferences when requesting images or detailed geometry information.
