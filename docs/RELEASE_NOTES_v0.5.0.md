## NovaSolver Studio 0.5.0 (preview)

The analyses and outputs you expect from a commercial tool — each new analysis comes with a template whose answer
is known in closed form, so Studio checks itself.

### New analyses
| Analysis | Template (reference) | Studio vs reference |
|---|---|---|
| **Natural frequencies and mode shapes** (modal) | Cantilever, Euler–Bernoulli beam | f₁ 206.5 vs 206.4 Hz (+0.05 %); f₃ −1.1 % |
| **Thermal stress** (uniform temperature, or a heat solve first) | Bar fixed at both ends, σ = EαΔT | 246 vs 246 MPa (0.00 %) |
| | Free bar, δ = αΔT L | 0.120 vs 0.120 mm (0.00 %) |
| **Self-weight** (gravity) | Hanging bar, σ = ρgL | 76.99 vs 77.01 kPa (−0.03 %) |
| **Rotation** (centrifugal load) | Rotating disk centre, (3+ν)/8 ρω²R² | 35.58 vs 35.51 MPa (+0.20 %) |
| **Torque on a face** | Shaft torsion, τ = 16T/πd³ and φ = TL/GJ | 63.67 vs 63.66 MPa; 0.016148 vs 0.016148 rad |

Also new: **bearing load** on a cylindrical face (cosine pressure on the loaded half) and **remote force** at a point;
both put exactly the force and moment you specify into the part.
Free-free modal analysis skips the rigid-body modes, also for several separate parts. Mode shapes play as an animation.

### Results you can share
- **Section view**: cut the part with a plane and read values on the cut face (quadratic elements evaluated exactly).
- **Export**: VTU for ParaView (quadratic tetrahedra with every field), CSV, and a **one-page analysis report**
  (HTML, prints to PDF): setup, faces and conditions from two sides, materials, mesh, results, and how far the
  answer is verified (reference or mesh-convergence GCI) — in Japanese, English or Chinese.
- AI assistants get the same through the new MCP tool `export_results` (24 tools).

### Safer verification
- A textbook comparison is only made when the case matches the textbook: adding gravity, rotation or a temperature
  load to the cantilever now tells you why the reference no longer applies instead of "verified".

---

## NovaSolver Studio 0.5.0（プレビュー版）

商用ソフトで当たり前に使う解析と出力を加えました。新しい解析にはどれも答えのわかっているテンプレートを付け、Studio が自分で検算します。

### 新しい解析
| 解析 | テンプレート（参照解） | Studio と参照解 |
|---|---|---|
| **固有振動数と振動モード** | 片持ち梁（オイラー・ベルヌーイはり理論） | 1次 206.5 / 206.4 Hz（+0.05 %）、3次 −1.1 % |
| **熱応力**（一様な温度、または熱解析の温度分布） | 両端を拘束した棒 σ = EαΔT | 246 / 246 MPa（0.00 %） |
| | 自由な棒の伸び δ = αΔT L | 0.120 / 0.120 mm（0.00 %） |
| **自重**（重力） | 吊るした棒 σ = ρgL | 76.99 / 77.01 kPa（−0.03 %） |
| **回転**（遠心力） | 回転円板の中心 (3+ν)/8 ρω²R² | 35.58 / 35.51 MPa（+0.20 %） |
| **面へのトルク** | 丸棒のねじり τ = 16T/πd³、φ = TL/GJ | 63.67 / 63.66 MPa、0.016148 / 0.016148 rad |

ほかに、円筒面の**軸受荷重**（荷重側の半周に余弦分布の圧力）と、離れた点に加える**リモート荷重**を追加しました。どちらも指定した力とモーメントをそのまま部品に加えます。支えのない固有振動解析では、剛体として動くモードを除きます（複数の部品が離れていても正しく数えます）。振動モードはアニメーションで見られます。

### 共有できる結果
- **断面表示**：平面で切って、切り口の値を読めます（2次要素をそのまま評価）。
- **書き出し**：ParaView 用の VTU（2次四面体・全結果）、CSV、そして **1ページの解析レポート**（HTML、PDF に印刷可）。設定、表と裏から見た面と条件、材料、メッシュ、結果、どこまで検証できているか（参照解またはメッシュ収束 GCI）を、日本語・英語・中国語でまとめます。
- AI アシスタントも新ツール `export_results` で同じものを出せます（ツールは 24 個）。

### 検証をより正直に
- 教科書の解との比較は、条件が教科書と同じときだけ行います。片持ち梁に重力・回転・温度の荷重を足すと、「検証済み」ではなく、参照解が使えない理由を表示します。
