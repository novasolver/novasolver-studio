# Gemini CLI extension / Gemini CLI 拡張 / Gemini CLI 扩展

## English

Requires Gemini CLI, Python 3.10+ and `uv` on PATH. Install this repository's extension:

```sh
gemini extensions install https://github.com/novasolver/novasolver-studio
```

Review the requested access before accepting. Restart Gemini CLI, inspect `/extensions list` and `/mcp`, and try:

> Create a new coarse cantilever example, solve it, and report the displacement, units and reference-check status. Do not modify an existing case.

The extension uses the existing locked Studio 0.7.6.post1 launcher. The first run downloads packages from PyPI and needs write access to the extension directory. It does not require a NovaSolver account. Gemini authentication is separate. It does not change your existing MCP configuration; an existing server named `novasolver-studio` in Gemini settings takes precedence.

Simulation is local, but tool responses sent to Gemini include engineering values and requested images. Read the [data-handling policy](https://github.com/novasolver/novasolver-studio/blob/main/docs/PRIVACY.md). Do not use confidential models without permission from their owner. This release has no Genesis or topology-optimization tools. Solver completion, numerical convergence, mesh convergence and reference checks are separate; none establishes design safety.

Remove the extension with `gemini extensions uninstall novasolver-studio`.

The first connection may take longer while dependencies are downloaded and initialized. If `/mcp` reports disconnected, check that `uv --version` works, then restart Gemini CLI and check `gemini mcp list` again. Do not remove other MCP entries or disable permission checks to troubleshoot.

## 日本語

Gemini CLI、Python 3.10以上、PATH上の `uv` が必要です。上のコマンドで導入し、権限の内容を確認してから承認してください。Gemini CLIを再起動し、`/extensions list` と `/mcp` で確認します。

例：「新しい片持ち梁の粗いメッシュの例題を作成して解析し、変位・単位・参照値との比較結果を報告してください。既存ケースは変更しないでください。」

解析はローカルで行いますが、結果の数値や要求した画像はGemini側に渡ります。公開版にGenesisは含まれません。計算完了・数値収束・メッシュ収束・参照値検証を区別して確認してください。

## 中文

需要 Gemini CLI、Python 3.10 以上，以及 PATH 中的 `uv`。使用上面的命令安装，检查权限后再确认。重启 Gemini CLI，通过 `/extensions list` 和 `/mcp` 检查扩展和连接。

示例：“创建一个新的粗网格悬臂梁案例并求解，报告位移、单位及参考值验证结果。不要修改已有案例。”

求解在本机进行，但工具返回的数值及请求的图片会传给 Gemini。此公开版本不包含 Genesis。请分别检查求解完成、数值收敛、网格收敛和参考值验证；它们不代表设计安全认证。

## Validation scope — 2026-11-13

- Windows: Gemini CLI 0.68.0 installed and enabled the extension in an isolated profile using a local copy of its manifest, context and locked launcher files.
- Gemini CLI `mcp list` reported Connected after dependency preparation. Earlier cold-start checks reported Disconnected; first-run readiness is not instantaneous.
- Direct MCP invocation using this manifest's launcher: 35 tools; new coarse cantilever solved; numerical convergence and reference verification passed.
- A Gemini model has not performed the simulation in this test. macOS/Linux installation and public GitHub installation have not yet been tested. This is not a claim of official Gemini directory listing.

Format reference: https://geminicli.com/docs/extensions/reference/
Support: https://github.com/novasolver/novasolver-studio/issues (public; do not include confidential data). Private contact: info@novasolver.jp.
