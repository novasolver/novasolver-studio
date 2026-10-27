import type { ResultsPayload } from "../api/types";

/** Inputs echoed back as cards (not results). */
const INPUT_KEYS = new Set(["re"]);
/** Bookkeeping numbers (quiet group at the end). */
const META_KEYS = new Set(["nodes", "elements", "iterations"]);
/** Near-duplicates of the colour-bar maximum. */
const DUP_KEYS = new Set(["max_disp"]);

/** Result cards split for display: the lead figure (the one compared with the reference), outputs, inputs, bookkeeping. */
export function splitCards(r: ResultsPayload) {
  const v = r.verification;
  const close = (a: number, b: number) => Math.abs(a - b) <= Math.max(Math.abs(a), Math.abs(b)) * 2e-3;
  const inputs = r.cards.filter((c) => INPUT_KEYS.has(c.key));
  const meta = r.cards.filter((c) => META_KEYS.has(c.key));
  let outputs = r.cards.filter((c) => !INPUT_KEYS.has(c.key) && !META_KEYS.has(c.key) && !DUP_KEYS.has(c.key));
  const lead = (v && outputs.find((c) => close(c.value, v.computed))) || outputs[0] || null;
  outputs = outputs.filter((c) => c !== lead);
  return { inputs, lead, outputs: outputs.slice(0, 3), meta: meta.slice(0, 1), compared: !!(v && lead && close(lead.value, v.computed)) };
}
