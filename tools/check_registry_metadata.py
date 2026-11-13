"""Check local MCP distribution metadata before publishing (no network or credentials)."""
import json
import re
import argparse
import urllib.request
from pathlib import Path


def check(root):
    root = Path(root)
    data = json.loads((root / "server.json").read_text(encoding="utf-8"))
    alternate = json.loads((root / "server.pypi.json").read_text(encoding="utf-8"))
    if data != alternate:
        raise ValueError("server.pypi.json must match server.json; do not restore an old template")
    source = (root / "backend/novastudio/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*[\"\']([^\"\']+)', source)
    if not match:
        raise ValueError("Studio version not found")
    version = match.group(1)
    packages = data["packages"]
    pypi = [p for p in packages if p["registryType"] == "pypi"]
    bundles = [p for p in packages if p["registryType"] == "mcpb"]
    if len(pypi) != 1 or len(bundles) != 1:
        raise ValueError("Keep both the PyPI launcher and Windows MCPB distribution")
    package = pypi[0]
    expected = {
        "identifier": "novasolver-studio", "version": version,
        "runtimeHint": "uvx", "registryBaseUrl": "https://pypi.org",
        "transport": {"type": "stdio"},
        "packageArguments": [{"type": "positional", "value": "mcp"}],
    }
    for key, value in expected.items():
        if package.get(key) != value:
            raise ValueError(f"Invalid PyPI {key}")
    bundle = bundles[0]
    expected_url = ("https://github.com/novasolver/novasolver-studio/releases/download/"
                    f"v{version}/novasolver-studio-{version}-win64.mcpb")
    if bundle.get("identifier") != expected_url:
        raise ValueError("MCPB release does not match Studio version")
    if not re.fullmatch(r"[0-9a-f]{64}", bundle.get("fileSha256", "")):
        raise ValueError("Missing or invalid MCPB SHA-256")
    marker = f'<!-- mcp-name: {data["name"]} -->'
    if marker not in (root / "README.md").read_text(encoding="utf-8"):
        raise ValueError("Missing PyPI ownership marker in README")
    return data


def check_published(data, fetch=None):
    package = next(p for p in data["packages"] if p["registryType"] == "pypi")
    url = f'https://pypi.org/pypi/{package["identifier"]}/{package["version"]}/json'
    if fetch is None:
        def fetch(address):
            with urllib.request.urlopen(address, timeout=30) as response:
                return json.load(response)
    info = fetch(url)["info"]
    if info["version"] != package["version"]:
        raise ValueError("Published PyPI version mismatch")
    pattern = r'mcp-name:\s*' + re.escape(data["name"]) + r'(?=\s|<|-->|$)'
    if not re.search(pattern, info.get("description") or ""):
        raise ValueError("Published PyPI README lacks the ownership marker; publish corrected package metadata first")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--published", action="store_true", help="Also check public PyPI version and ownership")
    args = parser.parse_args()
    data = check(Path(__file__).resolve().parents[1])
    if args.published:
        check_published(data)
    print("PASS: both distributions, launcher, versions and ownership metadata")
