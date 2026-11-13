# Gemini CLI extension / Gemini CLI 拡張 / Gemini CLI 扩展

## English

Requires Gemini CLI, Python 3.10+ and `uv` on PATH. Install this repository's extension:

```sh
gemini extensions install https://github.com/novasolver/novasolver-studio --ref main
```

Review the requested access before accepting. Restart Gemini CLI and inspect `/extensions list` and `/mcp`.

Use `--ref main`: older Studio application releases do not contain the extension manifest. If Gemini's GitHub downloader fails, use a regular Git clone and install that local checkout:

```sh
git clone --depth 1 --branch main https://github.com/novasolver/novasolver-studio.git
gemini extensions install ./novasolver-studio
```

For this local-copy installation, update the checkout with `git -C novasolver-studio pull --ff-only` and reinstall from the same folder when you want an update. Do not disable TLS certificate verification to resolve download errors.

Then try: "Create a new coarse cantilever example, solve it, and report the displacement, units and reference-check status. Do not modify an existing case."

Extension 0.2.0 uses the locked Studio 0.8.0 launcher shared with the Claude Code plugin. The first run downloads packages from PyPI and needs write access to the extension directory. It does not require a NovaSolver account. Gemini authentication is separate. It does not change your existing MCP configuration; an existing server named `novasolver-studio` in Gemini settings takes precedence.

Simulation is local, but tool responses sent to Gemini include engineering values and requested images. Read the [data-handling policy](https://github.com/novasolver/novasolver-studio/blob/main/docs/PRIVACY.md). Do not use confidential models without permission from their owner. Studio 0.8.0 exposes 37 tools, including `run_genesis` and `genesis_result` for topology optimization. Genesis seeks a higher-stiffness or lower-temperature shape under the specified conditions, without guaranteeing a global optimum. Re-import exported STL/STEP for normal analysis and analyse the smoothed STL separately; optimization results do not validate exported or smoothed geometry. Solver completion, numerical convergence, mesh convergence and reference checks are separate; none establishes design safety.

Remove the extension with `gemini extensions uninstall novasolver-studio`.

The first connection may take longer while dependencies are downloaded and initialized. If `/mcp` reports disconnected, check that `uv --version` works, then restart Gemini CLI and check `gemini mcp list` again. Do not remove other MCP entries or disable permission checks to troubleshoot.

## 日本語

Gemini CLI、Python 3.10以上、PATH上の `uv` が必要です。上のコマンドで導入し、権限の内容を確認してから承認してください。Gemini CLIを再起動し、`/extensions list` と `/mcp` で確認します。

例：「新しい片持ち梁の粗いメッシュの例題を作成して解析し、変位・単位・参照値との比較結果を報告してください。既存ケースは変更しないでください。」

解析はローカルで行いますが、結果の数値や要求した画像はGemini側に渡ります。Studio 0.8.0はGenesisの `run_genesis`・`genesis_result` を含む37ツールを提供します。Genesisは指定条件のもとで剛性の高い形や温度を下げる形を探索し、大域的最適解を保証しません。最適化結果は書き出した形状や平滑化した形状の検証にはなりません。書き出したSTL/STEPを再読込して通常の解析を行い、平滑化したSTLも別途解析してください。計算完了・数値収束・メッシュ収束・参照値検証を区別して確認してください。いずれも設計の安全性を保証するものではありません。

## 中文

需要 Gemini CLI、Python 3.10 以上，以及 PATH 中的 `uv`。使用上面的命令安装，检查权限后再确认。重启 Gemini CLI，通过 `/extensions list` 和 `/mcp` 检查扩展和连接。

示例：“创建一个新的粗网格悬臂梁案例并求解，报告位移、单位及参考值验证结果。不要修改已有案例。”

求解在本机进行，但工具返回的数值及请求的图片会传给 Gemini。Studio 0.8.0 提供37个工具，包括 Genesis 的 `run_genesis` 和 `genesis_result`。Genesis 在指定条件下寻找刚度更高或温度更低的形状，不保证全局最优解。优化结果不代表已验证导出或平滑后的几何形状。请重新导入导出的 STL/STEP 进行常规分析，并单独分析平滑后的 STL。请分别检查求解完成、数值收敛、网格收敛和参考值验证；它们不代表设计安全认证。

## Locked launcher validation — Studio 0.8.0, 2026-11-13

- Windows / Python 3.12 / uv 0.13.8: direct stdio MCP using this manifest's exact locked launcher arguments exposed 37 tools, including `run_genesis` and `genesis_result`, and passed `environment_check`.
- A fresh coarse cantilever in a private workspace solved with numerical convergence and its reference check passing. The shared Claude launcher passed the same independent smoke test in a separate workspace.
- No Gemini/Claude authentication or model calls were used. Genesis optimization, mesh studies, external solvers and assistant-client installation were not retested for this update.
- The targeted lock update preserved existing third-party packages and added Studio's required `tomli` dependency for Python below 3.11. Downloads retained native TLS verification; the stdio tests ran with uv offline.

## Historical validation — Studio 0.7.6.post1, 2026-11-13

- Windows: Gemini CLI 0.68.0 installed and enabled the extension in an isolated profile using a local copy of its manifest, context and locked launcher files.
- Gemini CLI `mcp list` reported Connected after dependency preparation. Earlier cold-start checks reported Disconnected; first-run readiness is not instantaneous.
- Direct MCP invocation using this manifest's launcher: 35 tools; new coarse cantilever solved; numerical convergence and reference verification passed.
- Public-source retrieval through regular `git clone` and local extension installation passed. Direct GitHub installation in Gemini CLI failed on this PC because its Git subprocess could not find its CA bundle; the documented clone-and-install route avoids that failure without disabling TLS verification.
- The public-source installation also reported Connected in Gemini CLI after dependency initialization.
- A Gemini model has not performed the simulation in this test. macOS/Linux installation has not yet been tested. This is not a claim of official Gemini directory listing.

Format reference: https://geminicli.com/docs/extensions/reference/
Support: https://github.com/novasolver/novasolver-studio/issues (public; do not include confidential data). Private contact: info@novasolver.jp.
