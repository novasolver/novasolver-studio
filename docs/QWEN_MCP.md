# Studio with Qwen Code / Qwen Code 連携 / Qwen Code 集成

## 中文

先安装 Qwen Code、Python 3.10 以上和 uv。在启动 Qwen Code 的终端执行 `uvx --version`，确认能够找到命令。首次运行需要从 PyPI 下载依赖。

以下示例固定为 Studio 0.8.0（包含 Genesis），必须等此版本发布到 PyPI 后才能运行；只有源码或 GitHub 发布包还不够。

先检查 `qwen mcp list`。如果已经有 `novasolver-studio`，请检查现有配置，不要覆盖。否则可以注册：

```sh
qwen mcp add --scope user --transport stdio novasolver-studio uvx novasolver-studio==0.8.0 mcp
```

这会修改 Qwen 的用户配置。也可以把下方 JSON 中的服务器条目合并到现有 `~/.qwen/settings.json` 的 `mcpServers`，保留其他设置。不要用示例覆盖整个文件。

安装依赖后再执行 `qwen mcp list`。0.27.2 的连接检查有 10 秒期限；第一次下载可能显示超时。可先运行 `uvx novasolver-studio==0.8.0 --help` 完成依赖准备，再重试。不要关闭 TLS 校验或放宽工具权限来解决下载问题。

## 日本語

Qwen Code、Python 3.10 以上、uv が必要です。Qwen を起動するターミナルで `uvx --version` を確認してください。上の登録コマンドはユーザー設定を変更するため、先に `qwen mcp list` で既存の Studio 登録を確認し、重複させないでください。

例は Genesis を含む Studio 0.8.0 に固定しています。同じバージョンが PyPI に公開されている必要があり、ソースや GitHub の配布物だけでは実行できません。

手動設定では下のサーバー項目だけを既存の `mcpServers` に統合します。設定ファイル全体を上書きしないでください。初回の依存ダウンロードが接続確認の10秒を超える場合は、上の `--help` コマンドで準備を済ませてから再確認します。

## English

Install Qwen Code, Python 3.10+ and uv. Confirm `uvx --version` in the terminal used to launch Qwen. Check `qwen mcp list` before running the registration command above; do not replace an existing Studio entry. Registration changes user settings.

These examples pin Studio 0.8.0, including Genesis. That exact version must be published on PyPI first; a source checkout or GitHub release alone is insufficient.

For manual setup, merge only this server entry into the existing `mcpServers` object in `~/.qwen/settings.json`. Preserve other settings. Qwen Code 0.27.2's connection probe has a 10-second limit; prepare the dependencies with the `--help` command above if the initial download exceeds it, then retry.

```json
{
  "mcpServers": {
    "novasolver-studio": {
      "command": "uvx",
      "args": ["novasolver-studio==0.8.0", "mcp"]
    }
  }
```

## Workspace and privacy / 作業場所と情報の扱い / 工作区与隐私

- If you use a custom Studio workspace, add `"env": {"NOVASTUDIO_WORKSPACE": "<absolute workspace path>"}` inside the server entry. Replace the placeholder. Do not assume the client forwards every environment variable from its parent terminal. The GUI and MCP need the same workspace to see the same cases.
- 独自の作業フォルダを使う場合は、サーバー設定内の `env` に `NOVASTUDIO_WORKSPACE` を明示してください。GUI と MCP で同じ場所を指定すると、同じ解析ケースが見えます。
- 使用自定义工作区时，请在服务器配置的 `env` 中明确设置 `NOVASTUDIO_WORKSPACE`，并与 GUI 保持一致。
- Simulation runs locally, but results read by a hosted AI assistant go to its provider. 解析はローカルですが、AI が取得する結果は AI 提供元へ送られます。计算在本机运行，但 AI 读取的结果会发送给 AI 服务提供商。See [data handling](https://github.com/novasolver/novasolver-studio/blob/main/docs/PRIVACY.md).

## Verification scope — 2026-11-13

This historical verification used **novasolver-studio==0.7.6.post1**, not the 0.8.0 examples now shown above; it does not validate the new PyPI release or Genesis. With Qwen Code **0.27.2**, Node **24.15.0**, Windows and an isolated `QWEN_HOME`, `qwen mcp list` reported **Connected** after dependencies were prepared. The test used an explicit isolated workspace/cache in the server's `env`; existing personal settings were not changed. The initial cold connection timed out. Qwen emitted a Node-version warning, but the connection check succeeded.

An additional **Qwen Code + DeepSeek Flash** run completed a real workflow: template listing → new coarse cantilever → preview solve → result retrieval. All four Studio tool calls succeeded, with no permission denials. The local result file independently confirms `ran=true`, `converged=true`, `verified=true`, `verified_by=reference`; no mesh-convergence study was run. The assistant reported the fixed-support stress-singularity warning and did not claim the design was safe.

This test used a synthetic case, a dedicated workspace, a five-tool Studio allowlist and credentials supplied only through the process environment. It did not change personal client settings. DeepSeek was the model provider **inside Qwen Code**; this is not a test of an Alibaba Qwen model or its OAuth plan. macOS/Linux and mainland-China package retrieval remain untested. This guide is not an official catalog listing.

Qwen Code を DeepSeek Flash に接続した実機テストでは、片持ち梁の作成・解析・結果取得まで成功しました。参照値との照合が通った結果であり、メッシュ収束や設計の安全性を確認したものではありません。Alibaba の Qwen モデルでの解析は未検証です。

Qwen Code 使用 DeepSeek Flash 的实际测试已完成悬臂梁创建、求解和结果读取。参考值校验通过，但没有执行网格收敛研究，也不代表设计安全。尚未测试阿里巴巴 Qwen 模型。

[Official Qwen MCP documentation](https://qwenlm.github.io/qwen-code-docs/en/users/features/mcp/)
