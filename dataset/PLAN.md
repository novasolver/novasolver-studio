# Certified physics space: 12-hour run plan (2026-11-02, about 13:00 to 01:00)

The machine: i7-7700 (4 cores, 8 threads), 16 GB, about 4 GB free while the desktop apps run. The mesher and the
solver each use one core, so 4 points run at once (`--workers 4`). Each step is resumable: an append-only
`points.jsonl` per family, cases deleted after their numbers are read.

| # | Step | Est. | Exit check |
|---|------|------|------------|
| 1 | L-bracket v2 (fillet R/16, study R/8-R/16-R/32), 300 points | 0.7 h | 300 ok; stress band < 3 % at p95 |
| 2 | Make build/analyze family-generic (family module = geometry, loads, measurement, theory) | while 1 runs | v2 summary identical before/after |
| 3 | Plate with a central hole in tension: choose mesh level (probe at r/4..r/32), compare with Kirsch / Howland-Pilkey | 0.5 h | thin-plate Kt within 2 % of Pilkey |
| 4 | Plate with a hole: 200 points (3 parameters) | 1.5-2 h | all checks pass; flags explained |
| 5 | Third family with an exact anchor: thick-walled cylinder under internal pressure (Lame) + a stepped shaft with a shoulder fillet (Peterson charts) | 3-4 h | Lame within 0.5 %; shaft Kt trend vs Peterson |
| 6 | L-bracket plasticity correction: elastic-plastic solves on a subset (load curve per point) | 3-4 h | only if Studio's nonlinear solver passes a hand check (bar yield, plastic hinge) first |
| 7 | Package: per-family README/data card, an index of all families (the "map"), Hugging Face layout | 0.5 h | CSV/JSON only; total size reported |

Rules kept: no production server use, no cron/task changes, studio code commits only for dataset/ (out/ is ignored).
If free memory falls below ~1 GB, drop to 3 workers. Each family is reported with the same table: points, time,
size, error band, checks, neighbour flags, direction checks.
