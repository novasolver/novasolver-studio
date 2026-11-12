# Codex setup in Studio

Open the AI panel and use **Codex integration**. Studio previews the current
`CODEX_HOME/config.toml` (or `~/.codex/config.toml`). You can enter another absolute
`config.toml` path and preview it. Reading status does not create files.

Review the path and proposed TOML, then click **Add Studio to Codex**. Only this
button sends the write request. The backend revalidates the preview revision and
refuses changed, invalid, conflicting, symlinked or inaccessible configurations.
Existing matching entries, including disabled entries and approval preferences,
are left unchanged. An adjacent backup preserves the original bytes and Windows
access rules; keep backups private because they may contain credentials.
Restart Codex after setup.

The shared writer is `novastudio.codex_mcp`, included in the Python package.
`tools/configure_codex_mcp.py` is a source-checkout CLI wrapper around that writer.
The GUI calls HTTP routes through `commands.py`; no setup tool is exposed to MCP.
Python 3.10 uses the conditional `tomli` dependency.

Setup does not launch commands, install software, access the network, or alter
network/authentication settings. The existing setup recipe uses `uvx` and pins
`novasolver-studio==0.7.6.post1`. Install uv separately; Codex may fetch that package
when it starts MCP. This recipe does not point at the running source checkout or
validate Codex connectivity. UI errors intentionally omit configuration contents.

Tests must use synthetic temporary configurations and override `CODEX_HOME`.
Windows ACL tests require an execution environment permitted to copy file ACLs;
the writer fails closed if it cannot preserve them.
