"""Explicit-path Codex MCP setup; dry-run unless --apply is supplied."""
from pathlib import Path
import argparse
import sys

# Source checkout entry point; the reusable implementation ships in novastudio.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from novastudio.codex_mcp import ARGS, TABLE, configure, plan

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True, help='Explicit target config.toml path')
    parser.add_argument('--apply', action='store_true', help='Write after validation; default is dry-run')
    options = parser.parse_args()
    try:
        print(configure(options.config.expanduser().absolute(), options.apply))
    except (ValueError, OSError):
        # TOML/OS exceptions can contain user data; do not echo their contents.
        parser.exit(1, 'Configuration was not updated. Check TOML validity, duplicate Studio entries, permissions and concurrent edits.\n')


if __name__ == '__main__':
    main()
