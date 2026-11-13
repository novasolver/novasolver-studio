# PyPI trusted publishing setup

PyPI trusted publishing is configured and Studio 0.8.0 is published. The steps below describe the setup; do not recreate an existing account or publisher.

1. Create the PyPI account under the NovaSolver business name and enable two-factor authentication.
2. On pypi.org, add a pending trusted publisher for project `novasolver-studio`:
   GitHub owner `novasolver`, repository `novasolver-studio`, workflow `publish-pypi.yml`, environment `pypi`.
3. Create the GitHub repository environment `pypi`; configure required reviewers to gate releases.
4. Review the version in `backend/novastudio/__init__.py`, run CI, then run the workflow by hand (Actions → Publish Python
   package → Run workflow). After that first success, add `push: tags: ['v*']` to its `on:` block so that releases
   publish themselves.
5. After each successful PyPI release, keep both the Windows MCPB and PyPI entries in `server.json`.
   The PyPI entry needs `runtimeHint: uvx` and the positional `mcp` argument. Update `server.pypi.json`
   to the same contents, then run `python tools/check_registry_metadata.py` before publishing.
   The registry workflow also checks this to prevent a release from dropping the PyPI launcher.

Registry metadata revision `0.8.1-registry.1` refers to the existing **Studio 0.8.0** packages;
it is not a new application release. Registry 0.8.0 was already published without the PyPI entry
and is immutable. A prerelease of the next patch sorts after 0.8.0 and before a future 0.8.1.
The proposed registry update is blocked until the referenced PyPI package description contains
the ownership marker: the published 0.8.0 description currently lacks it. The source README
already contains the marker, but changing GitHub does not change an existing PyPI description.
A metadata-corrected Python post-release is required; retain the 0.8.0 Windows MCPB.
Do not dispatch Registry publication until `python tools/check_registry_metadata.py --published`
passes for the chosen package version. The post-release and its version alignment are not
implemented by this metadata-only change.
See the [registry versioning rules](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/versioning.mdx).

Local release check: install the `dev` extra, run `npm ci` in `frontend`, then
`python tools/build_wheel.py` and `python tools/smoke_wheel.py`. Artifacts go to ignored `dist-py/`.
