# NovaSolver Studio for Antigravity

Use an AI assistant to create engineering cases, import CAD/STL, set conditions, run local
analysis and explain results. The server includes 37 MCP tools, including Genesis topology
optimization. The `simulate` skill keeps assumptions and different kinds of verification explicit.

## Prerequisites and installation

Install Python 3.10+ and [uv](https://docs.astral.sh/uv/getting-started/installation/), then verify
`uvx --version` in the terminal that launches Antigravity. Prepare the published package:

```sh
uvx novasolver-studio==0.8.0.post1 --help
```

From this repository checkout, validate and install the plugin folder:

```sh
agy plugin validate --strict ./plugins/novasolver-antigravity
agy plugin install ./plugins/novasolver-antigravity
agy plugin list
```

Installation changes the selected Antigravity profile. In Antigravity, check the MCP connection
and ask for a coarse cantilever example. This folder is a custom plugin, not evidence of an
approved Google Marketplace listing. External solvers are optional and require their own setup.

The plugin pins Studio 0.8.0.post1, a Python metadata revision of 0.8.0. Initial startup downloads
dependencies from PyPI. Cases go under the plugin's persistent `${PLUGIN_DATA}/cases` directory,
not its read-only installation folder. Use the same `NOVASTUDIO_WORKSPACE` when launching the
Studio GUI if you want to inspect these cases there. Do not replace existing MCP configuration files.

## Data handling and support

Analysis runs on your computer. Tool responses and requested result images may be sent to the
AI provider configured in Antigravity. Local execution does not make the entire AI conversation
offline. Review your provider's policy before using confidential models or results.

- [Privacy policy](https://github.com/novasolver/novasolver-studio/blob/main/docs/PRIVACY.md)
- [Public support and bug reports](https://github.com/novasolver/novasolver-studio/issues)
- Private contact: [info@novasolver.jp](mailto:info@novasolver.jp)

GitHub reports are public. Omit personal details, credentials and confidential CAD data.
Numerical convergence, mesh convergence and reference comparisons are separate checks;
none certifies that a design is safe. Reanalyse exported and smoothed optimization geometry.

## Validation status

Validated with Antigravity CLI 1.5.7: strict plugin validation reported no findings, and
installation into an isolated profile succeeded. The configured `uvx` command exposed 37
MCP tools; a direct MCP cantilever run completed with numerical convergence and a reference
comparison. An Antigravity model-driven session and a mesh-convergence study were not run.
This is a tested local integration, not a claim of marketplace approval or design certification.

## 日本語

Python 3.10以上とuvを用意し、上記のコマンドで依存関係を準備してから導入します。
解析はPC上で実行しますが、AIが読む結果や画像はAI提供元へ送られる場合があります。
解析完了、数値収束、メッシュ収束、参照値との照合を区別して説明します。
Google公式掲載・安全認証を意味するものではありません。

## 中文

需要 Python 3.10 或更新版本及 uv。先准备依赖，再按上述命令安装插件。
解析在本机执行，但 AI 读取的结果或图片可能发送给所配置的模型提供商。
求解完成、数值收敛、网格收敛和参考结果校核是不同检查，均不代表设计安全认证。
本目录是自定义插件，不表示已获 Google Marketplace 收录。
