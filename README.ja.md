# NovaSolver Studio

**AI アシスタントに任せられる、無料・ローカルの解析ソフト。答えは毎回、理論解とメッシュ収束で確かめます。**
構造（FEM）・熱・流れ（CFD）を、CalculiX・OpenFOAM®・内蔵の2次四面体ソルバで、あなたの PC の中だけで解きます。
MCP に対応しているので、Claude などの AI が STEP/STL の読み込みから荷重の設定、計算、メッシュの細分化、検証まで進めます。

[English](README.md) · [中文](README.zh.md) ·
**[ブラウザで試す（インストール不要）](https://novasolver.jp/studio/demo/)** ·
[Windows 版をダウンロード](https://github.com/novasolver/novasolver-studio/releases/latest) ·
[novasolver.jp/studio](https://novasolver.jp/studio/)

![AI が歯車の歯を設定して解き、メッシュを3段階で細かくし、手計算と比べるまで](assets/readme/studio-demo.gif)

*AI にひとこと頼む → Studio が条件を設定して解く → メッシュを3段階で細かくして収束を確認（GCI 1.5%）→ 手計算と比較。実際のアプリと実際の数値です。*

## Studio の特長

- **「計算できた」と「正しい」を分けます。** 結果には「実行できた → 収束した → 検証済み」の3つの判定が別々につきます。
  テンプレートは解析解や文献値と、読み込んだ形状はメッシュ収束（Roache の GCI）で自動的に確かめます。
  AI には「検証に合格するまで正しいと言わない」よう指示しています。降伏を超えた応力や、鋭い角の応力特異点などの警告も伝えます。
- **形状は PC の外に出ません。** アカウント・アップロード・利用状況の収集はありません。通信は更新の確認と例題のダウンロードだけで、
  オフラインモードではそれも止まります。ほかのコードが通信を始めると公開テストが失敗します。
  クラウドの AI と機密の部品を扱うときは **「数値のみモード」** で、部品の画像も AI に渡しません。→ [docs/PRIVACY.md](docs/PRIVACY.md)
- **本物のソルバを無料で。** 構造・熱は CalculiX、流れ・水冷は OpenFOAM®、数秒で答える内蔵 FEM。画面は日本語・英語・中国語。
- **AI 用の道具は型付きの 30 ツール、シェル実行なし。** AI は解析条件の表を埋めるだけで、ソルバの入力は Studio が書きます。
  AI の変更は画面にそのまま表示され、元に戻せます。

## 確かめている例

| 例 | 比べる相手 | Studio |
|---|---|---|
| 片持ち梁の先端たわみ | 梁理論（曲げ＋せん断） | −0.9%（内蔵 FEM。[ブラウザ体験版](https://novasolver.jp/studio/demo/)でも同じ） |
| 円柱と平板の接触圧 | ヘルツの線接触 | −0.04%（0.7 の接触解析） |
| 球の抗力（外部流れ） | Schiller–Naumann の式 | +0.3%（OpenFOAM®） |
| 水冷プレート | 熱収支 | 0.03% |

全件の一覧（許容誤差・メッシュ収束の列つき）は、リリースごとに `docs/VALIDATION.md` として公開します。

## できること

構造（線形静解析・固有値・塑性や大変形の非線形・座屈・接触・疲労）、熱伝導と熱応力、静電場・直流電流とジュール発熱、
内部流れ・外部流れ・水冷（伝熱連成）。STEP / IGES / BREP / STL を読み込めます。
[Blender アドオン](integrations/blender/)、3D プリントの強度チェック（PLA・PETG・ABS で、印刷の向きごとに積層の弱さも考えた安全率を出し、最も強い向きを示します）、ParaView 用 VTU・CSV・印刷できる HTML レポートの出力、
`.nscase` の関連付けつきインストーラもあります。

## 使い方

- **Windows**: [Releases](https://github.com/novasolver/novasolver-studio/releases/latest) からインストーラか zip を入手。
- **Claude Desktop**: Releases の `.mcpb` を開くと拡張機能として入ります。MCP Registry にも `io.github.novasolver/novasolver-studio` で登録しています。
- **Python（macOS / Linux / Windows）**、ソースからの起動、ほかの MCP クライアントの設定は [README（英語）](README.md#install-with-python-macos--linux--windows) を見てください。

ライセンスは GPL-3.0 です。OpenFOAM® は OpenCFD Ltd. の登録商標で、本ソフトは OpenCFD の承認を受けたものではありません。
