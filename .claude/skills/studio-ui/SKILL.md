---
name: studio-ui
description: Rules and verification loop for any visual change to the NovaSolver Studio frontend (studio/frontend). Use before editing components, tokens (index.css), the 3D viewer's look (viewer/palette.ts, Viewer.ts lighting/grid), or i18n strings shown in the UI.
---

# Studio UI — keep it quiet, precise and readable

Mode: **Operate** (a tool people work in for hours), not a landing page. The source of
truth for values is `studio/docs/DESIGN.md` §2.4 → `frontend/src/index.css` (CSS variables)
and `frontend/src/viewer/palette.ts` (3D colours). Never hard-code a hex in a component.

## Tokens and colour
- Use roles, not swatches: `bg` (chrome), `surface` / `field`, `raised`, `sunken`, `overlay`,
  `line` / `line-strong`, `fg` / `fg-2` / `fg-3`. One chrome ground for top bar, step list,
  properties panel and status bar; the viewport is the sheet inside it.
- Accent (cyan) only for: focus ring, current step number, viewport selection/hover, slider
  fill, links. Not for nav fills, side bars, section icons or category labels. Under ~5 % of pixels.
- Primary button = `bg-primary text-primary-ink` (near-black / near-white). One per view.
- Status colours (`green`, `orange`, `red`) for text, icons and pale tints (`*-soft`) only.
  Never a saturated fill behind white text.
- Every text tier ≥ 4.5:1 on every ground it sits on (placeholders included); icons, control
  borders and focus rings ≥ 3:1. Run a contrast check for each new token pair.

## Type
- Scale: `text-micro` 11, `text-label` 12, `text-body` 13, `text-em` 14, `text-kpi` 16,
  `text-lead` 20, `text-page` 24. Weights 400 / 500 / 600 only.
- Numbers: `tnum`, right-aligned in columns, unit after the value at 0.8× in `fg-3`
  (`unitLabel()` turns `degC` → `°C`, `W/m2` → `W/m²`).
- Labels sentence case; no tracked uppercase, no eyebrow kickers, no decorative numbering.
- CJK: letter-spacing 0 (global rule), never below 12 px, `prose-ui` / `text-callout` give
  1.65 line height in JA/ZH. Check that JA/ZH strings do not overflow fixed widths.

## Surfaces, space, motion
- Border **or** shadow, never both on resting surfaces. Shadows only on `overlay` and the
  viewport `.hud`. Radii: 4 chips, 6 controls, 8 panels/HUD, 10 start-screen cards.
- Group, don't box: related numbers share one container split by 1 px dividers.
  Sections are separated by 24 px of space, not rules. No card inside a card.
- 4 px grid; controls 32 px high (28 in dense lists).
- Motion 100 / 160 / 220 ms with `--ease-out`; animate opacity/transform only, never
  `transition: all`; focus rings are never animated; respect `prefers-reduced-motion`.

## Data and viewport
- Results strip: one lead figure (the one compared with the reference) at `text-lead`,
  then outputs, then quiet bookkeeping; inputs (e.g. Re) in a separate chip.
- Colour bar 200 × 8 with five ticks (explicit 0 for diverging maps).
- Viewer stays framework-free and cheap on Intel HD 630: no post-processing, few draw
  calls, render on demand. Ground grid/shadow is one analytic quad; outlines are fat lines
  on the face boundary only. New looks go into `palette.ts` for both themes.
- Face lists must scale to hundreds of faces: search, role filter chips (also the legend),
  grouping, compact rows, multi-select, hover/pick sync with the 3D view.

## Forbidden ("generated UI" tells)
Gradient text, purple/indigo gradients, glow, decorative glass; icons in tinted circles;
coloured left bars thicker than 1 px; accent-tinted nav rows; 36–48 px bold KPIs; sparkline
on every number; emoji or Unicode glyphs as icons (use lucide, `stroke-width 1.5`);
monospace as costume; "nothing here" empty states without a next action.

## Verification loop (required before reporting)
1. `npm run build` in `studio/frontend` — zero TypeScript errors.
2. Dev server (`npm run dev`, backend on :8765; mock fallback if it is down). Take 1440×900
   Playwright screenshots of start, boundaries with a picked face, running, results
   (cantilever, cavity, one imported sample) and the yield warning in **JA dark, JA light,
   EN light, ZH dark** into `frontend/screenshots/v2/`. `window.__nss` (dev only) exposes
   the store for scripting.
3. Collect console errors and page errors: must be zero.
4. Review the screenshots against these rules, fix, and repeat at least twice.
5. Keep `i18n/{ja,en,zh}.json` key sets identical; run `npm run build` again at the end.

## Sources (read, not copied)
Values distilled in `research_notes/UIデザイン洗練/design_skills.md` from:
[pbakaus/impeccable](https://github.com/pbakaus/impeccable) (Apache-2.0),
[Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) (MIT),
[Nutlope/hallmark](https://github.com/Nutlope/hallmark) (MIT),
[vercel-labs/web-interface-guidelines](https://github.com/vercel-labs/web-interface-guidelines) (MIT),
[ibelick/ui-skills](https://github.com/ibelick/ui-skills) (MIT),
[anthropics/skills](https://github.com/anthropics/skills) (Apache-2.0),
and the [Linear UI redesign write-up](https://linear.app/now/how-we-redesigned-the-linear-ui).
