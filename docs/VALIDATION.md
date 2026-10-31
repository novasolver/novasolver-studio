# NovaSolver Studio 検証マニュアル — 0.7.0

この文書は、Studio 0.7.0 が既知の答えのある問題をどれだけ正しく解くかの記録です。すべての問題は `validation/suite.py` で誰でも再計算できます。数値は 2026-10-31 に下記の環境で解いた結果で、手で書き写したものではありません。

環境: Windows-10-10.0.19045-SP0, Python 3.12.3, 8 CPU

## まとめ

43 題中 43 題が許容差内（不合格 0・エラー 0・参照値なし 0）。

判定欄の「メッシュ収束」は、粗・標準・細の3段階メッシュで答えが変わらないこと（GCI）を Studio 自身が確認したものです。「1メッシュ」はメモリなどの理由で1段階だけ解いたものです。

## 構造

| 題材 | 確かめること | 量 | Studio | 参照値 | 差 | 許容差 | 判定 | メッシュ |
|---|---|---|---|---|---|---|---|---|
| 片持ち梁 | 一端を固定した角棒の先端に荷重をかけ、たわみと応力を求めます。梁理論の手計算と自動で比較します。 | Tip deflection (beam theory with shear correction) | 0.9762 mm | 0.9831 mm | -0.70 % | ±3 % | 合格 | 収束確認済み |
| 穴あき板の引張 | 中央に穴のある板を引っ張り、穴の縁の応力集中係数を Heywood の式と比較します。 | Stress concentration Kt (Heywood) | 2.541 - | 2.512 - | +1.16 % | ±5 % | 合格 | 収束確認済み |
| 片持ちはりの固有振動 | 鋼製はりの固有振動数をオイラー・ベルヌーイはり理論の解析解と比較します。 | Steel beam modes compared with the Euler–Bernoulli beam solution. | 206.5 Hz | 206.4 Hz | +0.04 % | ±2 % | 合格 | 収束確認済み |
| 柱の座屈（一端固定・他端自由） | 細長い角柱の先端に圧縮荷重をかけ、座屈荷重をオイラーの式と比較します。 | Euler critical load, fixed-free column. | 2638 N | 2634 N | +0.12 % | ±2 % | 合格 | 収束確認済み |
| 柱の座屈（両端固定） | 両端を固定した角柱を軸方向に縮め、座屈荷重をオイラーの式と比較します。 | Euler critical load, column clamped at both ends. | 4.196e+04 N | 4.215e+04 N | -0.46 % | ±2 % | 合格 | 収束確認済み |
| 棒の疲労（グッドマン） | 棒を 0 ↔ 15 kN で繰り返し引っ張り、疲労安全率をグッドマンの式と比べます。 | Goodman diagram n = 1/(σa/Se + σm/Su). | 1.778 - | 1.778 - | -0.00 % | ±1 % | 合格 | 収束確認済み |
| 両端拘束棒の熱応力 | 軸方向のみを両端で拘束。熱応力をEαΔTと比較します。 | Axial restraint at both ends; compare thermal stress with EαΔT. | 246 MPa | 246 MPa | +0.00 % | ±2 % | 合格 | 収束確認済み |
| 棒の自由熱膨張 | 横方向の膨張を妨げず、伸びをαΔTLと比較します。 | Allow lateral expansion and compare elongation with αΔTL. | 0.12 mm | 0.12 mm | -0.00 % | ±1 % | 合格 | 収束確認済み |
| 自重で伸びる棒 | 自重による応力と伸びを一次元の解析解で検証します。 | Verify self-weight stress and displacement against the one-dimensional solution. | 1.878e-04 mm | 1.878e-04 mm | -0.00 % | ±2 % | 合格 | 収束確認済み |
| 回転円板 | 対称な1/4・半厚さモデル。中心応力を平面応力の解析解と比較します。 | Quarter disk with half thickness; compare centre stress with the plane-stress solution. | 35.54 MPa | 35.51 MPa | +0.07 % | ±2 % | 合格 | 収束確認済み |
| 丸棒のねじり | 鋼製丸棒のトルクによるせん断応力とねじれ角を検証します。 | Verify shear stress and twist of a steel shaft under torque. | 0.01615 rad | 0.01615 rad | +0.00 % | ±2 % | 合格 | 収束未確認 |
| 大変形片持ちはり | 伸びを無視した Euler エラスティカ、PL²/EI = 1。線形解と比較します。 はり端拘束は横ひずみを許容します。 | Inextensible Euler elastica, PL²/EI = 1; compare with the linear answer. The beam clamp permits lateral strain. | 60.22 mm | 60.34 mm | -0.20 % | ±2 % | 合格 | 収束確認済み |
| 弾塑性棒 | 一軸の二直線硬化。1% まで載荷し、力がゼロになる点を経て変位ゼロに戻します。 | Uniaxial bilinear hardening: load to 1%, unload through zero force, then return to zero displacement. | 268 MPa | 268 MPa | -0.00 % | ±1 % | 合格 | 収束確認済み |
| はりの塑性崩壊 | 完全塑性の矩形片持ちはり。せん断を無視し P = σy b h²/(4L)。限界到達時は未収束で終了します。 はり端拘束は横ひずみを許容します。 | Perfectly plastic rectangular cantilever; P = σy b h²/(4L), neglecting shear. A limit run ends without convergence. The beam clamp permits lateral strain. | 1280 N | 1250 N | +2.44 % | ±3 % | 合格 | 1メッシュ |
| ゴムの引張り | 圧縮性 neo-Hookean 材料の一様引張り。λ = 2、側面応力ゼロの厳密解で検証します。 | Homogeneous compressible neo-Hookean tension, λ = 2 and zero lateral stress. | 29.54 MPa | 29.54 MPa | +0.00 % | ±2 % | 合格 | 収束確認済み |
| 圧入 | Lamé の厚肉円筒・平面応力。接触圧力とリングの周方向応力を検証します。 | Lamé thick cylinders, plane stress. Contact pressure and ring hoop stress. | 76.92 MPa | 76.88 MPa | +0.06 % | ±2 % | 合格 | 収束確認済み |
| 積層ブロック | 接触する 2 個の立方体の一様圧縮。摩擦なしの接触を検証します。 | Uniform compression of two touching cubes; frictionless contact. | 4000 N | 4000 N | -0.00 % | ±0.5 % | 合格 | 収束確認済み |
| 摩擦ブロック | 圧力とせん断を受ける Coulomb 摩擦。柔らかいばねで滑り後も支持します。 一様状態の検証にはポアソン比 0 を用います。 | Coulomb stick/slip under normal pressure and shear, with a soft spring. This patch uses Poisson ratio 0. | 400 N | 400 N | -0.00 % | ±1 % | 合格 | 収束確認済み |
| すき間のある2つのブロック（接触） | すき間 0.05 mm で離れた2つのブロックを押しつけます。メッシュは上下で異なり、すき間が閉じた後の接触力を手計算と比べます。 | Uniform compression of two blocks in series: F = E (d − g) A / (2h). | 1.025e+05 N | 1.025e+05 N | -0.00 % | ±0.5 % | 合格 | 収束確認済み |
| 別々にメッシュした部品の固着 | 節点を共有しない2つのブロックを接着（固着）して引っ張り、1本の棒と同じ答えになることを確かめます。 | Uniform tension of one bar: F = E d A / (2h). | 1.025e+05 N | 1.025e+05 N | -0.00 % | ±0.5 % | 合格 | 収束確認済み |
| 円柱と平面の接触（ヘルツ） | 鋼の円柱を鋼のブロックに押しつけ、最大接触圧力と接触幅をヘルツの式と比べます（平面ひずみ・1/4モデル）。 | Hertz line contact p0 = √(P E*/(πR)) and the contact half-width a. | 1407 MPa | 1408 MPa | -0.09 % | ±5 % | 合格 | 収束確認済み |
| NAFEMS LE1 楕円膜 | 曲線境界・対称面・外向き圧力 | σyy at D | 92.8 MPa | 92.7 MPa | +0.11 % | ±2 % | 合格 | 収束確認済み |
| NAFEMS LE10 厚板の曲げ | 3次元の曲げ・成分拘束・対称面 | σyy at D | -5.364 MPa | -5.38 MPa | -0.29 % | ±2 % | 合格 | 1メッシュ |
| 閉じた厚肉円筒の内圧（Lamé） | 曲面への圧力・2次要素の曲面追従・1/8対称 | hoop stress, mid wall | 20 MPa | 19.99 MPa | +0.01 % | ±1 % | 合格 | 収束未確認 |
|  |  | axial stress, mid wall | 9.756 MPa | 9.756 MPa | +0.00 % | ±1 % | 合格 |  |
| 曲がり梁（Winkler–Bach） | 曲げと軸力の組合せ・曲率による応力の偏り | inner fibre | 90.6 MPa | 89.41 MPa | +1.33 % | ±2 % | 合格 | 収束確認済み |
|  |  | outer fibre | -51.92 MPa | -52.2 MPa | -0.54 % | ±2 % | 合格 |  |
| 鋼とアルミの直列棒 | 部品ごとの材料・成分拘束・部品間の接合面 | tip displacement | 0.1934 mm | 0.1937 mm | -0.17 % | ±1 % | 合格 | 収束確認済み |
| 厚肉球の内圧 | 3方向の対称面・曲面の内圧 | inner displacement | 0.00195 mm | 0.001951 mm | -0.07 % | ±1 % | 合格 | 収束確認済み |
|  |  | hoop stress at the bore | 7.136 MPa | 7.143 MPa | -0.10 % | ±3 % | 合格 |  |

## 伝熱

| 題材 | 確かめること | 量 | Studio | 参照値 | 差 | 許容差 | 判定 | メッシュ |
|---|---|---|---|---|---|---|---|---|
| 熱伝導ブロック | 両端の温度を固定した直方体の中を伝わる熱。フーリエの法則（Q = kAΔT/L）と自動で比較します。 | Heat flow through the block (Fourier's law) | 40 W | 40 W | +0.00 % | ±2 % | 合格 | 収束確認済み |
| 冷却フィン | 根元を加熱し、周りの空気で冷やされる棒状フィン。根元から逃げる熱量をフィン理論の解析解と比較します。 | Heat through the fin base (fin theory) | 5.064 W | 5.066 W | -0.05 % | ±2 % | 合格 | 収束確認済み |
| NAFEMS T4 対流つき2次元伝熱 | 温度固定と対流の組合せ | T at E | 18.25 °C | 18.3 °C | -0.28 % | ±1 % | 合格 | 収束確認済み |
| ISO 10211 附属書A ケース1 | 建築熱橋計算法の検証（許容 0.1 K） | largest deviation of 28 points (at x 1 m, y 7 m) | 9.657 °C | 9.658 °C | -0.000693 °C | ±0.1 °C | 合格 | 収束未確認 |
| ISO 10211 附属書A ケース2（4材料の熱橋） | 複数材料・薄いアルミ部材・表面熱抵抗 | T at A | 7.065 °C | 7.1 °C | -0.035 °C | ±0.1 °C | 合格 | 1メッシュ |
|  |  | T at B | 0.7613 °C | 0.8 °C | -0.0387 °C | ±0.1 °C | 合格 |  |
|  |  | T at C | 7.898 °C | 7.9 °C | -0.00191 °C | ±0.1 °C | 合格 |  |
|  |  | T at D | 6.272 °C | 6.3 °C | -0.0279 °C | ±0.1 °C | 合格 |  |
|  |  | T at E | 0.8275 °C | 0.8 °C | +0.0275 °C | ±0.1 °C | 合格 |  |
|  |  | T at F | 16.41 °C | 16.4 °C | +0.00842 °C | ±0.1 °C | 合格 |  |
|  |  | T at G | 16.33 °C | 16.3 °C | +0.0343 °C | ±0.1 °C | 合格 |  |
|  |  | T at H | 16.77 °C | 16.8 °C | -0.0329 °C | ±0.1 °C | 合格 |  |
|  |  | T at I | 18.33 °C | 18.3 °C | +0.0336 °C | ±0.1 °C | 合格 |  |
|  |  | heat flow | 9.492 W/m | 9.5 W/m | -0.00779 W/m | ±0.1 W/m | 合格 |  |
| 3層の壁 | 部品ごとの熱伝導率・接合面での温度の連続 | T, first interface | 19.85 °C | 19.85 °C | -1.82e-12 °C | ±0.05 °C | 合格 | 収束確認済み |
|  |  | T, second interface | 0.7634 °C | 0.7634 °C | -4.39e-12 °C | ±0.05 °C | 合格 |  |
|  |  | heat flow | 0.1527 W | 0.1527 W | +0.00 % | ±1 % | 合格 |  |
| 円管の半径方向伝熱 | 曲面の温度条件・対数分布 | T at r = 15 mm | 53.21 °C | 53.2 °C | +0.00481 °C | ±0.05 °C | 合格 | 収束確認済み |
|  |  | heat flow | 1813 W | 1813 W | +0.00 % | ±1 % | 合格 |  |

## 電気

| 題材 | 確かめること | 量 | Studio | 参照値 | 差 | 許容差 | 判定 | メッシュ |
|---|---|---|---|---|---|---|---|---|
| 平行平板コンデンサ | 平板間の電位と静電容量を求め、C = εA/d と比較します。 | Capacitance (parallel-plate solution) | 23.24 pF | 23.24 pF | -0.00 % | ±1 % | 合格 | 収束確認済み |
| 同軸ケーブル | 同軸導体間の静電容量と電界を求め、円筒の解析解と比較します。 | Capacitance (coaxial solution) | 0.9326 pF | 0.9326 pF | +0.00 % | ±1 % | 合格 | 収束確認済み |
| 母線のジュール発熱 | 銅棒の電流と発熱による温度上昇を求め、抵抗と熱伝導の解析解で確かめます。 | Temperature rise (bar with cooled ends) | 7.641 K | 7.641 K | -0.00 % | ±1 % | 合格 | 収束確認済み |

## 流れ

| 題材 | 確かめること | 量 | Studio | 参照値 | 差 | 許容差 | 判定 | メッシュ |
|---|---|---|---|---|---|---|---|---|
| キャビティ流れ | ふたが動く正方形の箱の中の流れ。CFDの標準問題で、Ghia らの参照値（Re=100）と比較します。 | Mean error of centreline u (Ghia et al. 1982, Re = 100) | -0.2134 m/s | -0.2109 m/s | +0.15 % | ±3 % | 合格 | 収束確認済み |
| 平行平板の流れ | 2枚の板の間を流れる層流。十分発達した速度分布が放物線（ポアズイユ流れ）になるかを確かめます。 | Outlet centre velocity (Poiseuille u_max = 1.5 U) | 0.01497 m/s | 0.015 m/s | -0.23 % | ±2 % | 合格 | 1メッシュ |

## 流れ

| 題材 | 確かめること | 量 | Studio | 参照値 | 差 | 許容差 | 判定 | メッシュ |
|---|---|---|---|---|---|---|---|---|
| 円管の層流（Hagen–Poiseuille） | 内部流れの壁摩擦・圧力勾配 | pressure gradient, developed flow | 5.115 Pa/m | 5.11 Pa/m | +0.10 % | ±2 % | 合格 | 収束確認済み |
| 急拡大管の損失（Borda–Carnot） | 乱流・はく離と再付着・壁の境界層メッシュ | loss coefficient K | 0.5592 - | 0.5625 - | -0.59 % | ±5 % | 合格 | 1メッシュ |
| 乱流の円管摩擦（Blasius） | 乱流の壁摩擦（壁関数・境界層メッシュ） | pressure gradient, developed flow | 5541 Pa/m | 5304 Pa/m | +4.48 % | ±10 % | 合格 | 1メッシュ |

## 外部流れ

| 題材 | 確かめること | 量 | Studio | 参照値 | 差 | 許容差 | 判定 | メッシュ |
|---|---|---|---|---|---|---|---|---|
| 球まわりの流れ（抗力） | 一様な流れの中に置いた球の抗力係数を求め、Schiller-Naumann の式（Re=100）と比較します。物体まわり流れの標準問題。 | Drag coefficient (Schiller-Naumann) | 1.1 - | 1.092 - | +0.79 % | ±8 % | 合格 | 収束確認済み |

## 分かっている限界

- 乱流の壁摩擦（円管の摩擦係数）は、壁の近くのメッシュに強く左右されます。表の Blasius の結果を確認してから使ってください。
- 固定面の角や鋭い入隅の応力は理論上無限大（特異点）です。Studio は警告を出し、比べる値には使いません。
- NAFEMS LE10 の細かいメッシュは 16 GB のメモリでは解けないため、標準メッシュ1段階の値です。
- 接触・座屈・疲労は上の表の基本問題（直列ブロック・ヘルツ接触・オイラー座屈・グッドマン）で確かめています。陽解法の衝突・シェル要素は、この版の検証範囲に含まれていません。

## 出典

- **3層の壁**: Hand calculation: series thermal resistances
- **ISO 10211 附属書A ケース1**: ISO 10211:2017 Annex A, case 1 (28 grid points; exact series solution)
- **ISO 10211 附属書A ケース2（4材料の熱橋）**: ISO 10211:2017 Annex A, case 2: nine temperatures (±0.1 K) and 9.5 W/m (±0.1 W/m)
- **NAFEMS LE1 楕円膜**: NAFEMS, The Standard NAFEMS Benchmarks, TNSB Rev. 3 (1990), LE1: σyy at D = 92.7 MPa
- **NAFEMS LE10 厚板の曲げ**: NAFEMS TNSB Rev. 3, LE10: σyy at D = −5.38 MPa
- **NAFEMS T4 対流つき2次元伝熱**: NAFEMS TNSB Rev. 3, T4: T at E = 18.3 °C
- **すき間のある2つのブロック（接触）**: Uniform compression of two blocks in series: F = E (d − g) A / (2h).
- **はりの塑性崩壊**: Perfectly plastic rectangular cantilever; P = σy b h²/(4L), neglecting shear. A limit run ends without convergence. The beam clamp permits lateral strain.
- **キャビティ流れ**: Mean error of centreline u (Ghia et al. 1982, Re = 100)
- **ゴムの引張り**: Homogeneous compressible neo-Hookean tension, λ = 2 and zero lateral stress.
- **両端拘束棒の熱応力**: Axial restraint at both ends; compare thermal stress with EαΔT.
- **丸棒のねじり**: Verify shear stress and twist of a steel shaft under torque.
- **乱流の円管摩擦（Blasius）**: Blasius: f = 0.316 Re^−0.25 (Re 20,000), dp/dx = f/d · ρU²/2
- **円柱と平面の接触（ヘルツ）**: Hertz line contact p0 = √(P E*/(πR)) and the contact half-width a.
- **円管の半径方向伝熱**: Hand calculation: Q = 2πkLΔT / ln(b/a)
- **円管の層流（Hagen–Poiseuille）**: Hagen–Poiseuille: dp/dx = 32 μ U / d²
- **冷却フィン**: Heat through the fin base (fin theory)
- **別々にメッシュした部品の固着**: Uniform tension of one bar: F = E d A / (2h).
- **厚肉球の内圧**: Lamé solution for a thick sphere, Timoshenko & Goodier §141
- **同軸ケーブル**: Capacitance (coaxial solution)
- **回転円板**: Quarter disk with half thickness; compare centre stress with the plane-stress solution.
- **圧入**: Lamé thick cylinders, plane stress. Contact pressure and ring hoop stress.
- **大変形片持ちはり**: Inextensible Euler elastica, PL²/EI = 1; compare with the linear answer. The beam clamp permits lateral strain.
- **平行平板の流れ**: Outlet centre velocity (Poiseuille u_max = 1.5 U)
- **平行平板コンデンサ**: Capacitance (parallel-plate solution)
- **弾塑性棒**: Uniaxial bilinear hardening: load to 1%, unload through zero force, then return to zero displacement.
- **急拡大管の損失（Borda–Carnot）**: Borda–Carnot: K = (1 − A1/A2)² = 0.5625; turbulent, Re 10,000, k-ω SST
- **摩擦ブロック**: Coulomb stick/slip under normal pressure and shear, with a soft spring. This patch uses Poisson ratio 0.
- **曲がり梁（Winkler–Bach）**: Winkler–Bach curved-beam formula, e.g. Roark's Formulas for Stress and Strain, 8th ed., §9.1
- **柱の座屈（一端固定・他端自由）**: Euler critical load, fixed-free column.
- **柱の座屈（両端固定）**: Euler critical load, column clamped at both ends.
- **棒の疲労（グッドマン）**: Goodman diagram n = 1/(σa/Se + σm/Su).
- **棒の自由熱膨張**: Allow lateral expansion and compare elongation with αΔTL.
- **母線のジュール発熱**: Temperature rise (bar with cooled ends)
- **熱伝導ブロック**: Heat flow through the block (Fourier's law)
- **片持ちはりの固有振動**: Steel beam modes compared with the Euler–Bernoulli beam solution.
- **片持ち梁**: Tip deflection (beam theory with shear correction)
- **球まわりの流れ（抗力）**: Drag coefficient (Schiller-Naumann)
- **積層ブロック**: Uniform compression of two touching cubes; frictionless contact.
- **穴あき板の引張**: Stress concentration Kt (Heywood)
- **自重で伸びる棒**: Verify self-weight stress and displacement against the one-dimensional solution.
- **鋼とアルミの直列棒**: Hand calculation: u = F/A (L1/E1 + L2/E2)
- **閉じた厚肉円筒の内圧（Lamé）**: Lamé solution, e.g. Timoshenko & Goodier, Theory of Elasticity, §28

## 再計算の方法

Windows の zip 版または `pip install novasolver-studio` の環境で、リポジトリを取得して次を実行します。

```
python validation/suite.py
python validation/report.py validation/results/<version>.json
```
