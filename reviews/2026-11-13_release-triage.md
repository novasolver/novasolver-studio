# Release review triage — 2026-11-13

DeepSeek's first pass was advisory; findings were checked against source and actual runs.

| Finding | Disposition |
| --- | --- |
| STL import unit | Rejected: Genesis writes STL coordinates in metres; the recorded extents confirm a roughly 0.2 m specimen. Switching to mm would shrink it incorrectly. |
| End-plane tolerance | Rejected for this fixture: 1e-7 m exceeds float32 spacing near 0.2 m. Both retained planar ends were found in both exports; uncertain mapping fails closed. |
| Total-force rounding | Rejected: the relative tolerance allows 1e-5 N at 1000 N. All six measured loads and reactions pass. |
| Choosing the newest run by mtime | Fixed: the diagnostic now uses the exact returned job ID and refuses an already-failed job, preventing reuse of earlier results. Existing six run IDs were checked against their saved requests. |
| Large CAD import buffers | Deferred: the desktop link currently buffers uploaded CAD. No failing supported specimen was demonstrated. Streaming/size-limit UX needs a separate large-file test. |
| Missing signing-key environment variable | Non-blocking: it fails closed and cannot publish an unsigned notice. Artifact validation runs before key access. |
| Header sniff reads the entire download | Fixed: only 16 bytes are read. |
| File-link traversal within the local server | Fixed: case identity and the exact Genesis STEP/STL route are required; traversal, mismatched formats and fragments are rejected. Redirects/proxies are separately refused. |
| Legacy release-note language order | Rejected: the legacy format explicitly uses English/Japanese/Chinese order. New notes use validated language headings. |
| Missing job ID in command response | Rejected: both commands expose the documented job envelope; the actual optimisation and six analyses exercised it. Failed jobs now stop immediately. |

Independent release checks additionally reproduced and corrected STEP export unit state across OCCT sessions,
and found that the Codex integration recipe pinned an older package; it now follows the packaged Studio version.
Reference agreement and smoothing stiffness comparisons are not a strength or safety certificate.
