# Kimi Code / Kimi Code 接続 / Kimi Code 接入

## English

Install [Kimi Code](https://www.kimi.com/code/docs/en/kimi-code-cli/guides/getting-started.html),
Python 3.10+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).
Make `uvx` available on PATH. Prepare the published Studio environment once:

```sh
uvx novasolver-studio==0.8.0.post1 --help
```

In Kimi's interactive terminal, run:

```text
/plugins install https://github.com/novasolver/novasolver-studio/tree/main
/plugins info novasolver-studio
/new
/mcp
```

Use the explicit `tree/main` URL: the bare repository URL may select a Studio release
that predates this plugin. Review the local process and tool permissions before enabling it.
The plugin pins Studio 0.8.0.post1 and adds the `simulate` skill plus one local MCP server.
Kimi installs plugins for the current Kimi profile, across projects. Existing MCP entries
are not replaced. Avoid enabling another Studio connector at the same time.

Try: "Create a new coarse cantilever case, solve it, and report displacement, units,
numerical convergence and reference comparison. Do not modify existing cases."
The skill can also be invoked as `/skill:novasolver-studio:simulate`.

Cases use Studio's normal persistent workspace. To isolate them, set
`NOVASTUDIO_WORKSPACE` to your chosen absolute folder **before starting Kimi**.
Do not store cases inside Kimi's managed plugin directory, which may be replaced on upgrade.

If the first connection times out, run the preparation command above, verify Python/uv
availability, and start a new Kimi session. The manifest allows 120 seconds for startup
and 600 seconds per tool call. Long solver jobs return a job id and are polled separately.
Keep TLS verification enabled. Download access from mainland China has not been tested.

### Privacy and verification

Studio runs locally, but tool results or requested images included in a conversation can
reach the configured model provider. No NovaSolver account or API key is required for
the local server; Kimi's model login is separate. Do not share confidential CAD or personal
information in public issues. [Privacy policy](PRIVACY.md) ·
[Support](https://github.com/novasolver/novasolver-studio/issues) ·
[info@novasolver.jp](mailto:info@novasolver.jp).

Solver completion, numerical convergence, mesh convergence and reference comparisons
are separate checks. None certifies a design's real-world safety. Reanalyse exported or
smoothed optimization geometry before relying on it.

Validation on Windows, November 13, 2026: Kimi Code 2.6.1 installed the plugin in an
isolated profile with no manifest diagnostics, discovered one skill and connected to all
37 Studio tools using its own MCP connection probe. A separate direct MCP test of the
same launch command created and solved a cantilever and passed numerical convergence
and reference comparison. No Kimi model-driven conversation, Genesis optimization,
mesh-convergence study or macOS/Linux client run was performed. This is a directly
installable community plugin; it does not claim acceptance into Kimi's official marketplace.

## 日本語

Kimi Code、Python 3.10以上、PATH上のuvが必要です。上の準備コマンドで依存関係を
取得してから、Kimi内で導入コマンドを実行してください。`tree/main`を省略すると、
プラグイン追加前のリリースを取得する場合があります。導入先は現在のKimiプロファイルで、
複数のプロジェクトに適用されます。同じStudioを別のMCP設定でも二重に有効化しないでください。

検証済みなのはWindowsの隔離環境での導入・スキル認識・37ツールへの接続と、同じ起動
コマンドによる直接の片持ち梁解析です。Kimiモデルによる一連の操作や公式市場への掲載は
未確認です。計算はPC上でも、会話に含める結果や画像はモデル提供元へ送信される場合があります。
既存ケースを変更しない新規例題から始め、数値収束・メッシュ収束・参照値比較を区別してください。

## 中文

需要 Kimi Code、Python 3.10 以上以及 PATH 中的 uv。先运行上面的准备命令，
再在 Kimi 交互终端执行安装命令。保留 `tree/main`，避免选中尚未包含插件的旧版本。
插件安装在当前 Kimi 配置目录，适用于多个项目。不要同时启用另一份 Studio MCP 配置。

已在 Windows 隔离环境验证安装、技能识别及 37 个工具的连接，并用相同启动命令直接
完成悬臂梁计算、数值收敛与参考值比较。尚未验证 Kimi 模型驱动的完整流程、网格收敛
或中国大陆网络下载，也不表示已被官方市场收录。计算在本机进行，但会话中的结果和
图片可能发送给所配置的模型提供商。先创建新的测试案例，不要修改现有案例。

Official references: [plugins](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/plugins),
[MCP](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/mcp),
[local API used for testing](https://www.kimi.com/code/docs/en/kimi-code-cli/reference/server-api.html).
