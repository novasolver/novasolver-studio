# 開発者向けメモ

## 構成

```
backend/novastudio/
  commands.py     GUI・MCP・CLI が共通で呼ぶ唯一の操作層
  api.py          画面用 HTTP/WebSocket（127.0.0.1 のみ）
  mcp_server.py   MCP サーバ（stdio）
  store.py        ケース（case.json が唯一の正、変更ごとに revision）
  templates.py    テンプレート・材料・役割・参照解
  checks.py       準備チェック（解けない＝赤 / 注意＝橙）
  mesh_worker.py  Gmsh（必ず別プロセス）
  fem_tet10.py    内蔵プレビュー: 2次四面体の線形静解析・定常熱伝導（大規模は AMG-CG）
  cavity_fd.py    内蔵プレビュー: 2次元キャビティ流れ
  external.py     CalculiX / OpenFOAM の入力生成と実行（メモリ不足時は1回だけ自動再試行）
  flow3d.py       取込形状の内部流れ / 物体まわり（snappyHexMesh）/ 熱連成（chtMultiRegionSimpleFoam）
  jobs.py         切り離したジョブ（PID＋開始時刻で生存確認、停止可）
  run_worker.py   ジョブ本体。重い計算はマシン全体で1つずつ（solver.lock）。メッシュ収束（GCI）もここ
  results.py      ゲート・数値カード・検証・表示用の場・PNG
  i18n/           日本語・英語・中国語
backend/tests/    python -m pytest backend/tests -q
frontend/         画面（Vite + React + TypeScript + three.js）。規約は .claude/skills/studio-ui/
samples/          サンプル CAD（make_samples.py で再生成）
workspace/        ケースの保存先（NOVASTUDIO_WORKSPACE で変更可）
```

## 守ること

- GUI・MCP・CLI は commands.py だけを呼ぶ。AI にソルバの辞書を書かせず、スキーマを埋めさせる。
- Gmsh とソルバは別プロセス（GPL の集約・クラッシュ隔離）。
- 結果は ran / converged / verified。verified は安全の保証ではない（降伏超えは別警告）。
- メッシュの作り方を変えたら geometry.MESHER_VERSION を上げる（既存メッシュを作り直させる）。
- 公開物に個人名を入れない。コミット作者は `NovaSolver <info@novasolver.jp>`。
