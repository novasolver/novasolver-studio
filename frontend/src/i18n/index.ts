import ja from "./ja.json";
import en from "./en.json";
import zh from "./zh.json";
import type { Lang, Localized } from "../api/types";

export type Dict = Record<string, string>;
const DICTS: Record<Lang, Dict> = { ja, en, zh };
export const LANGS: Lang[] = ["ja", "en", "zh"];

export function translate(lang: Lang, key: string, vars?: Record<string, string | number>): string {
  let s = DICTS[lang][key] ?? DICTS.en[key] ?? DICTS.ja[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(String(v));
  return s;
}

/** Pick a localized backend string ({ja,en,zh} object or plain string). */
export function pick(lang: Lang, v: Localized | undefined | null): string {
  if (v == null) return "";
  if (typeof v === "string") return v;
  return v[lang] ?? v.en ?? v.ja ?? Object.values(v)[0] ?? "";
}

export function detectLang(): Lang {
  try {
    const saved = localStorage.getItem("nss.lang");
    if (saved === "ja" || saved === "en" || saved === "zh") return saved;
  } catch {
    /* ignore */
  }
  const nav = (navigator.language || "ja").toLowerCase();
  if (nav.startsWith("zh")) return "zh";
  if (nav.startsWith("ja")) return "ja";
  return nav.startsWith("en") ? "en" : "ja";
}
