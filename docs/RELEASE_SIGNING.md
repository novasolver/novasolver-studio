# Windows の警告を消す — 署名とストア配布の手順

Windows で「Windows によって PC が保護されました」（SmartScreen）が出るのは、配布物に信頼できる署名が無いためです。
有料の証明書は使わず、次の 2 つの無料の経路で解消します。どちらも **ビルドは GitHub Actions**
（`.github/workflows/release-windows.yml`）で行い、手元の PC で作ったバイナリは配布しません。

| 経路 | 対象 | 警告 | 運営者の作業 |
|---|---|---|---|
| A. SignPath Foundation | zip・インストーラ（GitHub / novasolver.jp から配布） | 署名済みになる。評判が貯まるまで初期は表示されることがある | 申請・承認者の登録 |
| B. Microsoft Store（MSIX） | ストアからのインストール | 出ない（ストアが署名） | Partner Center 登録・提出 |

企業の情シス向けには B（ストア、または MSIX の社内配布）が最も通りやすく、A は zip を直接配る場合の補強です。

---

## 共通：ビルドの流れ（Claude 側で用意済み）

```
build ジョブ          PyInstaller でプログラムフォルダを作る（-Stage app）
                      CalculiX / MS-MPI は SHA-256 を固定して取得・照合
                      exe env で起動確認 → 未署名フォルダを成果物として保存
sign-and-package     （A が有効なら）exe を SignPath で署名
                      zip + インストーラ（Inno Setup）を作成（-Stage package）
                      （B が有効なら）MSIX を作成
                      （A が有効なら）インストーラも署名し、SHA-256 を作り直す
```

- 実行: GitHub の Actions 画面で「Windows release build」→ Run workflow、または `v0.7.0` のようなタグを push。
- 成果物はワークフローの実行結果に添付されるだけで、**自動では公開しません**。中身を確認してからリリースへ載せます。
- 自動更新用の署名（ed25519、`tools/sign_latest.py`）は従来どおり手元で行います（鍵を GitHub に置かないため）。

### 同梱するソルバの取得

CI は CalculiX と MS-MPI を**元の配布元から**取得し、SHA-256 を照合します（`tools/fetch_build_deps.py`）。
今の配布 zip に同梱しているものとバイト単位で同一であることを確認済みです（2026-10-31）。

- CalculiX 2.23 Windows 版（dhondt.de、GPL-2.0）の `ccx_static.exe`
- MS-MPI 10.1 ランタイム（conda-forge のビルド、元は github.com/microsoft/Microsoft-MPI、MIT）

---

## A. SignPath Foundation（無料のコード署名）

オープンソース（OSI 承認ライセンス）向けに、SignPath Foundation 名義の証明書で無料署名する制度です。
Studio は GPL-3.0 なので対象です。証明書の発行元表示は「SignPath Foundation」になります。

### 運営者の作業

1. **申請**: https://signpath.org/ の「Apply」から申請。主な記入事項:
   - リポジトリ: `https://github.com/novasolver/novasolver-studio`
   - ライセンス: GPL-3.0-or-later
   - ビルド: GitHub Actions（GitHub ホストのランナー）でビルドしていること
   - 配布先: GitHub Releases、https://novasolver.jp/studio/
   - 連絡先は屋号と `info@novasolver.jp`（個人名は不要。求められた場合は応募フォームの非公開欄だけに）
2. **役割の登録**: 承認後、SignPath 側で「署名を承認する人（Approver）」を登録します。運営者 1 名で可。
   アカウントは 2 段階認証を有効にしてください。
3. **API トークン**: SignPath の画面で CI 用ユーザーの API トークンを発行し、GitHub の
   Settings → Secrets and variables → Actions に次を登録します。
   - Secret: `SIGNPATH_API_TOKEN`
   - Variables: `SIGNPATH_ORGANIZATION_ID`、`SIGNPATH_PROJECT_SLUG`（例 `novasolver-studio`）、
     `SIGNPATH_POLICY_SLUG`（例 `release-signing`）
4. 以後、リリースごとに SignPath から承認依頼が届くので、内容を見て承認します。

### SignPath 側の設定（Claude が用意、申請後に貼り付け）

プロジェクトに次の 2 つの Artifact configuration を作ります。

`program-folder`（PyInstaller のフォルダ。GitHub の成果物は zip で渡る）

```xml
<artifact-configuration xmlns="http://signpath.io/artifact-configuration/v1">
  <zip-file>
    <pe-file path="NovaSolverStudio.exe"><authenticode-sign/></pe-file>
  </zip-file>
</artifact-configuration>
```

`installer`

```xml
<artifact-configuration xmlns="http://signpath.io/artifact-configuration/v1">
  <zip-file>
    <pe-file path="*-setup.exe"><authenticode-sign/></pe-file>
  </zip-file>
</artifact-configuration>
```

### 公開ページへの表記（SignPath Foundation の条件）

README とダウンロードページに「コード署名ポリシー」の節を置きます（Claude が承認後に追加）。

> Free code signing provided by SignPath.io, certificate by SignPath Foundation.
> 署名対象は GitHub Actions でこのリポジトリからビルドしたものだけ。承認者: NovaSolver。

### 注意

署名しても、ダウンロード数が少ないうちは SmartScreen が出ることがあります（評判は証明書とファイルに貯まる）。
警告をすぐ確実に消したい場合は B（ストア）が確実です。

---

## B. Microsoft Store（MSIX）

ストア経由の MSIX は **Microsoft が署名**するので、自前の証明書が要りません。インストール時の警告は出ず、
更新もストアが自動で行います（アプリ内の自動更新はストア版では無効になり、ヘルプにその旨を表示します）。

### 運営者の作業

1. **Partner Center の開発者登録**: https://storedeveloper.microsoft.com/ から個人（Individual）で登録。
   表示名（Publisher display name）は **NovaSolver** にしてください（ストアに公開されます。個人名は使わない）。
   本人確認の情報は Microsoft に渡るだけで公開されません。登録料は申し込み画面の表示を確認してください。
2. **アプリ名の予約**: Partner Center →「新しい製品」→ MSIX or PWA app → 名前 `NovaSolver Studio`。
3. **Product identity の登録**: 予約後の「Product identity」画面にある 3 つの値を GitHub の Variables に登録。
   - `MSIX_IDENTITY_NAME`（Package/Identity/Name）
   - `MSIX_PUBLISHER`（Package/Identity/Publisher、`CN=...`）
   - `MSIX_PUBLISHER_NAME`（Package/Properties/PublisherDisplayName）
4. **提出**: ワークフローが作った `.msix` を「Packages」にアップロード。
   - 価格: 無料 / 市場: すべて
   - カテゴリ: 開発者ツール、または 教育
   - 制限付き機能の説明欄（`runFullTrust`、`unvirtualizedResources`）に次を記入:
     > Desktop engineering simulation app (Python + bundled CalculiX/OpenFOAM solvers). It starts solver
     > processes and a local web UI on 127.0.0.1, and shares cases and settings in the user's folders with its
     > command-line/MCP mode, so file-system virtualization is disabled.
   - プライバシーポリシー URL: `docs/PRIVACY.md` の公開ページ（novasolver.jp 側に置く。Claude が用意）
   - スクリーンショット: 既存の `frontend/screenshots/` から Claude が選定

### ストア版で確認すること（初回の審査前に Claude が実機で確認）

- 起動 → 専用ウィンドウ → 片持ち梁の計算 → 結果表示
- `.nscase` のダブルクリックで開く
- ターミナルから `NovaSolverStudio.exe mcp`（実行エイリアス）で MCP が応答する
- OpenFOAM の初回ダウンロードとフロー計算
- ヘルプの更新欄が「Microsoft Store が自動で更新します」になる

---

## winget（任意・A の後）

署名済みインストーラが出たら、winget-pkgs へマニフェストを PR すると `winget install NovaSolver.Studio`
で入るようになります。ストア版が公開されればストア ID でも winget から入ります。
