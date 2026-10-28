Implemented in `em-0.3`. **Commits: none** — Git refused to create `studio/.git/worktrees/studio_em/index.lock`; changes remain uncommitted.

| §8 | Computed vs reference | Result |
|---|---|---|
| 1 | C: 23.242243 pF / 23.242243 pF; centre E: 49,999.9997 / 50,000 V/m; V: 49.9999998 / 50 V | Pass; energy-based C agrees within 0.000001% |
| 2 | εr = 4: 44.270939 pF / 44.270939 pF | Pass |
| 3 | Coax C: 9.328364 / 9.325647 pF; peak E: 805,459 / 798,236 V/m | Errors 0.02913%, 0.90493% |
| 4 | Series C: 1.531254 / 1.531254 pF; interface V: 82.352941 / 82.352941 V | Pass |
| 5 | R: 33.557047 µΩ; power = Joule heat = 0.1192 W; ΔT: 0.0764102561 / 0.0764102564 K | Pass; current/heat imbalance 3.57×10⁻¹² / 3.78×10⁻⁹ |
| 6 | 1 A electrode voltage: 33.557047 / 33.557047 µV | Pass |
| 7 | Missing voltage, εr = 0.5, σ = −1 rejected | Pass |
| 8 | Capacitance study: 28,734 → 90,210 → 344,219 elements | Pass; GCI 2.89×10⁻¹⁴% ≤ 5% |
| 9 | Both MCP imports accepted; 21 tools retained | Pass |
| 10 | ja/en/zh: 292 backend keys, 357 frontend keys | Identical sets |

Full suite: **53 passed, 3 skipped, 0 failed**. OpenFOAM tests were skipped because it is unavailable. Tests used the specified Python environment and private `.tmp` lock, with BLAS threads limited to one.

`npm run build`: **passed, zero TypeScript errors**. This sandbox required an untracked esbuild pipe adapter.

[Release notes and detailed measurements](<E:/03_サイト構築/NovaSolver/studio_em/docs/RELEASE_NOTES_v0.3.0_draft.md>) are saved.

Unfinished: commits, and the [studio-ui](<E:/03_サイト構築/NovaSolver/studio_em/.claude/skills/studio-ui/SKILL.md>) requirement to “Take 1440×900 Playwright screenshots.” The helper timed out and headless Edge failed during IPC creation; visual QA remains unverified.