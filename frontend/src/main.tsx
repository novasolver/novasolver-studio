import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Fonts are bundled locally (offline app). Only the weights the UI uses.
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/noto-sans-jp/400.css";
import "@fontsource/noto-sans-jp/500.css";
import "@fontsource/noto-sans-jp/600.css";
import "@fontsource/noto-sans-sc/400.css";
import "@fontsource/noto-sans-sc/500.css";
import "@fontsource/noto-sans-sc/600.css";
import "./index.css";

import App from "./App";
import * as store from "./state/store";

void store.boot();

// dev-only handle for the screenshot loop (stripped from production builds)
if (import.meta.env.DEV) (window as unknown as { __nss: typeof store }).__nss = store;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
