## NovaSolver Studio 0.3.0 (preview)

Electromagnetics arrive: electrostatics and DC current, with optional Joule heating, on the same built-in solver as
heat conduction. No extra download is needed.

### New analyses
- **Electrostatics**: electrode voltages, surface charge, dielectrics. Capacitance, stored energy, field strength,
  with a warning when the field exceeds the rule-of-thumb breakdown of air (3 kV/mm).
- **DC current**: voltage or current on faces, insulated walls. Resistance, current, power and current density.
- **Joule heating**: the electrical losses heat the part; each face gets its own thermal condition (fixed
  temperature, convection or insulated). Reports the temperature rise.
- Works on imported STEP / IGES / BREP / STL parts, with copper, aluminium, steel, PTFE, alumina, glass and more
  (permittivity and conductivity), and per-body overrides.

### Templates with a known answer
- Parallel-plate capacitor: capacitance exact.
- Coaxial cable: 0.9328 pF against the analytic 2πε₀ε_r L / ln(b/a) = 0.9326 pF, +0.03 %.
- Copper busbar at 20 mV: Joule temperature rise 7.641 K against the 1-D solution, ±0.0 %.

### Correct readings at material boundaries
- Fields are recovered per material, so the field inside each dielectric layer is right up to the interface
  (checked within 1 % on both sides). Probes compute E = −∇V in the element that holds the point.
- Mesh studies track a response (capacitance, energy, temperature rise, resistance), never a prescribed input.

### Fixes
- On compact boxes (e.g. a 100 mm cube) the "normal" and "fine" meshes could be identical, so a mesh study could
  never pass. The requested element size is now honoured everywhere.
- Narrow windows: the results strip and brand mark no longer overlap the colour bar; colour-bar ticks for tiny
  ranges are readable.

### For AI assistants (MCP)
- The same 21 tools handle electrical cases: create from a template, set voltages / currents, run, read
  capacitance / resistance / temperature rise, probe fields and render images.

---

## NovaSolver Studio 0.3.0（プレビュー版）

電磁気の解析を追加しました。静電場と直流電流（ジュール発熱つき）を、熱伝導と同じ内蔵ソルバーで計算します。追加のダウンロードは不要です。

### 新しい解析
- **静電場**：電極の電圧・表面電荷・誘電体。静電容量・蓄えられるエネルギー・電界の強さを出します。空気の絶縁破壊の目安（3 kV/mm）を超えると警告します。
- **直流電流**：面に電圧または電流、絶縁面。抵抗・電流・電力・電流密度を出します。
- **ジュール発熱**：電気の損失で部品が温まります。面ごとに熱の条件（温度固定・対流・断熱）を選べ、温度上昇を出します。
- STEP / IGES / BREP / STL の取り込み部品で使えます。銅・アルミ・鋼・PTFE・アルミナ・ガラスなどの材料（誘電率・導電率）と、部品ごとの上書きに対応します。

### 答えのわかっているテンプレート
- 平行平板コンデンサ：静電容量が理論値と一致。
- 同軸ケーブル：0.9328 pF（理論式 2πε₀ε_r L / ln(b/a) = 0.9326 pF との差 +0.03 %）。
- 銅ブスバー（20 mV）：ジュール発熱による温度上昇 7.641 K（1次元の厳密解との差 ±0.0 %）。

### 材料の境目でも正しい値
- 電界を材料ごとに求めるので、誘電体の各層の中の電界が境目まで正しくなります（両側で 1 % 以内を確認）。点の値は、その点を含む要素で E = −∇V から計算します。
- メッシュ収束確認は、与えた値ではなく結果（静電容量・エネルギー・温度上昇・抵抗）で判定します。

### 修正
- 立方体のような寸詰まりの形（例：100 mm の立方体）で「標準」と「細かい」のメッシュが同じになり、収束確認が合格できないことがありました。指定した要素サイズがどこでも守られるようにしました。
- 幅の狭いウィンドウで、結果の帯とロゴがカラーバーに重ならないようにしました。範囲の小さいカラーバーの目盛りも読みやすくしました。

### AI 連携（MCP）
- これまでと同じ 21 個のツールで電気の解析も扱えます（テンプレートから作成・電圧や電流の設定・実行・静電容量や抵抗や温度上昇の読み取り・点の値・画像の出力）。
