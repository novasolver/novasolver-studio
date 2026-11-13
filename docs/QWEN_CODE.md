# Qwen Code / Qwen Code 接続 / Qwen Code 接入

## English

Requirements: [Qwen Code](https://qwenlm.github.io/qwen-code-docs/en/users/quickstart/),
Python 3.10+ and [uv](https://docs.astral.sh/uv/getting-started/installation/) on PATH.
Run the following in the workspace where you want to use Studio:

```sh
qwen extensions install https://github.com/novasolver/novasolver-studio:novasolver-studio --ref main --scope project
qwen extensions list
qwen mcp list
```

Review the installation prompt. The explicit plugin name avoids the repository's marketplace
selection prompt. Qwen Code 0.27.3 imports the repository's Gemini extension and reports
`Origin: Gemini`, version 0.2.0. This is client compatibility, not a separate Qwen marketplace listing.
The project scope enables the extension only for the current workspace. Personal Qwen
authentication is separate; no NovaSolver account is required.

### First connection times out

The initial download and installation can exceed Qwen's 10-second MCP discovery timeout.
If `qwen mcp list` reports a timeout, take the extension path shown by `qwen extensions list`
and prepare the locked environment once:

```sh
uv sync --locked --project "<extension-path>/plugins/novasolver-studio"
qwen mcp list
```

Replace `<extension-path>` with your actual displayed path. Keep TLS verification and the
lock file enabled. After it reports `Connected`, restart an existing Qwen session if needed.
Do not remove unrelated MCP settings. The shared launcher pins Studio 0.8.0 and exposes 37
tools, including Genesis topology optimization.

Try: "Create a new coarse cantilever case, solve it, and report displacement, units,
numerical convergence and the reference check. Do not modify existing cases."

Analysis runs locally. Tool responses and requested images can be sent to the model provider
configured in Qwen. See the [privacy policy](https://github.com/novasolver/novasolver-studio/blob/main/docs/PRIVACY.md).
Solver completion, numerical convergence, mesh convergence and reference comparisons are
different checks; none certifies design safety. Reanalyse exported and smoothed optimization geometry.

Validation on Windows, November 13, 2026: Qwen Code 0.27.3 installed the public GitHub
extension into a fresh isolated profile and enabled it for one workspace. The first connection
timed out; after the documented preparation, `qwen mcp list` reported `Connected`. The same
locked launcher has a separate direct MCP cantilever/reference smoke test recorded in
[GEMINI_CLI.md](GEMINI_CLI.md). No Qwen account, model-driven simulation, Genesis run,
mesh study or macOS/Linux client test was used in this compatibility check.

## 日本語

Qwen Code、Python 3.10以上、PATH上のuvが必要です。上の導入コマンドを使いたい
作業フォルダで実行し、表示された内容を確認して承認してください。対象ワークスペースだけで
有効になります。Qwenは既存のGemini拡張を読み込みます。公式カタログ掲載の意味ではありません。

初回に接続が10秒でタイムアウトする場合は、`qwen extensions list` のパスを使って上記の
`uv sync --locked` で依存関係を準備し、再度 `qwen mcp list` を確認します。
Windowsの隔離環境で公開GitHubからの導入・有効化・Connectedを確認済みです。
Qwenモデルによる一連の解析操作は未検証です。解析はPC上ですが、結果や画像は設定した
AI提供元へ送られる場合があります。既存ケースを変更しない新規の片持ち梁例題から試してください。

## 中文

需要 Qwen Code、Python 3.10 以上以及 PATH 中的 uv。在目标工作目录运行上面的安装命令，
检查提示后确认。扩展只在当前工作区启用。Qwen 会导入现有的 Gemini 扩展；这不表示已被
Qwen 官方市场收录，也不需要 NovaSolver 账号。Qwen 的模型登录是另一项设置。

首次连接可能因下载依赖超过10秒而超时。使用 `qwen extensions list` 显示的路径，运行上面的
`uv sync --locked`，再检查 `qwen mcp list`。不要关闭 TLS 校验或删除其他 MCP 配置。
已在 Windows 隔离环境验证公开 GitHub 安装、启用及 Connected；尚未验证 Qwen 模型驱动
的完整解析流程。解析在本机进行，但结果和图片可能发送给所配置的模型提供商。
建议先创建新的粗网格悬臂梁案例，并分别检查单位、数值收敛和参考值比较；这些不代表设计安全认证。

Support: [GitHub issues](https://github.com/novasolver/novasolver-studio/issues) (public),
or [info@novasolver.jp](mailto:info@novasolver.jp). Do not post confidential CAD or personal details in public issues.
