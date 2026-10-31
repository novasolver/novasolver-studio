# NovaSolver Studio — データの扱い / Data handling / 数据处理

## 日本語

**NovaSolver Studio は、形状・解析条件・結果を、お使いの PC の外へ送りません。**

- 解析はすべて PC の中で行います。内蔵ソルバー、CalculiX、OpenFOAM は、この PC で動く別プログラムです。
- 利用状況の収集（テレメトリ）、エラー報告の自動送信、アカウント登録、ライセンス認証はありません。
- 画面は Studio 自身が `127.0.0.1`（この PC の中だけの住所）で表示します。社内ネットワークの他の PC からは見えません。
- インターネットに接続するのは、次の2つだけです。どちらも「取りに行く」だけで、利用者やモデルの情報は何も送りません。
  1. 更新の確認と更新ファイルのダウンロード（1日1回。ヘルプでオフにできます）
  2. 解析例（例題）のダウンロード（例題一覧を開いたときだけ）
- **オフラインモード**：環境変数 `NOVASTUDIO_OFFLINE=1` を設定するか、`NovaSolverStudio.exe` と同じフォルダに `offline` という空のファイルを置くと、インターネットへ一切接続しません。

### どうやって確かめられるか

- **ソースコードはすべて公開しています**（GPL v3、https://github.com/novasolver/novasolver-studio）。どなたでも読み、自分でビルドできます。
- 通信するコードは `updates.py`（更新）と `examples.py`（例題）の2つのファイルだけです。それ以外のファイルが通信用のライブラリを使ったり、送信先のアドレスを増やしたりすると、自動テスト `tests/test_network_audit.py` が失敗します。このテストは公開リポジトリの一部で、リリースのたびに実行します。
- 配布ファイルには SHA-256 を添えて公開しています。ダウンロードしたファイルが改ざんされていないことを確かめられます。
- ファイアウォールで Studio の通信をすべて遮断しても、解析機能はすべて動きます（更新の確認と例題のダウンロードだけが止まります）。

### AI アシスタントと使う場合の注意

Studio を Claude などの AI アプリから操作する場合（MCP 連携）、AI に伝えた内容や AI が読み取った解析条件・結果は、**その AI アプリの提供元**へ送られます。これは Studio ではなく AI アプリ側の通信です。機密のモデルを扱うときは、社内の規程で認められた AI サービスだけを使うか、AI 連携を使わずに Studio の画面だけで操作してください。

---

## English

**NovaSolver Studio does not send your geometry, analysis settings or results off your computer.**

- Every analysis runs on your computer. The built-in solver, CalculiX and OpenFOAM are separate programs running locally.
- There is no telemetry, no automatic crash reporting, no account and no licence server.
- The interface is served by Studio itself on `127.0.0.1` (this computer only). It is not reachable from other computers on your network.
- Studio connects to the internet for exactly two things. Both only download; neither sends anything about you or your models.
  1. The update check and the update download (once a day; can be turned off in Help)
  2. The solved examples (only when you open the examples list)
- **Offline mode:** set `NOVASTUDIO_OFFLINE=1`, or put an empty file named `offline` next to `NovaSolverStudio.exe`, and Studio never connects to the internet.

### How you can check

- **All source code is public** (GPL v3, https://github.com/novasolver/novasolver-studio). Anyone can read it and build it.
- Only two files contain networking code: `updates.py` and `examples.py`. If any other file starts using a networking library, or a new outside address appears, the automated test `tests/test_network_audit.py` fails. The test is part of the public repository and runs for every release.
- Every release is published with its SHA-256, so you can check that a download has not been altered.
- If a firewall blocks all of Studio's network traffic, every analysis feature keeps working; only the update check and the example download stop.

### When you use an AI assistant

When Studio is driven from an AI app such as Claude (MCP), whatever you tell the AI, and the case settings and results it reads, are sent to **that AI app's provider**. That traffic belongs to the AI app, not to Studio. For confidential models, use only AI services your company has approved, or work in the Studio window without the AI connection.

---

## 中文

**NovaSolver Studio 不会把您的几何模型、分析条件和结果发送到您的电脑之外。**

- 所有分析都在您的电脑上进行。内置求解器、CalculiX 和 OpenFOAM 都是在本机运行的独立程序。
- 没有使用数据收集（遥测）、没有自动崩溃报告、没有账户注册，也没有许可证服务器。
- 界面由 Studio 自身在 `127.0.0.1`（仅限本机）提供，局域网中的其他电脑无法访问。
- Studio 只在以下两种情况下连接互联网，且都只是下载，不会发送任何关于您或模型的信息：
  1. 检查更新和下载更新（每天一次，可在“帮助”中关闭）
  2. 下载分析示例（仅在打开示例列表时）
- **离线模式**：设置环境变量 `NOVASTUDIO_OFFLINE=1`，或在 `NovaSolverStudio.exe` 所在文件夹放一个名为 `offline` 的空文件，Studio 将完全不连接互联网。

### 如何验证

- **全部源代码公开**（GPL v3，https://github.com/novasolver/novasolver-studio），任何人都可以阅读并自行构建。
- 只有 `updates.py` 和 `examples.py` 两个文件包含网络通信代码。如果其他文件使用网络库或增加了新的外部地址，自动测试 `tests/test_network_audit.py` 就会失败。该测试是公开仓库的一部分，每次发布时都会运行。
- 每个发布版本都附有 SHA-256，可以确认下载的文件未被篡改。
- 即使用防火墙阻断 Studio 的全部网络通信，所有分析功能仍可正常使用，只有检查更新和下载示例会停止。

### 与 AI 助手一起使用时

通过 Claude 等 AI 应用操作 Studio（MCP 连接）时，您告诉 AI 的内容以及 AI 读取的分析条件和结果，会被发送到**该 AI 应用的提供方**。这是 AI 应用的通信，而不是 Studio 的。处理机密模型时，请只使用公司批准的 AI 服务，或不使用 AI 连接，直接在 Studio 界面中操作。
