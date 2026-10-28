# PyPI trusted publishing setup

The operator must complete these steps before running the publish workflow. Nothing has been published yet.

1. Create the PyPI account under the NovaSolver business name and enable two-factor authentication.
2. On pypi.org, add a pending trusted publisher for project `novasolver-studio`:
   GitHub owner `novasolver`, repository `novasolver-studio`, workflow `publish-pypi.yml`, environment `pypi`.
3. Create the GitHub repository environment `pypi`; configure required reviewers to gate releases.
4. Review the version in `backend/novastudio/__init__.py`, run CI, then dispatch the workflow or push a matching `v*` tag.
5. After the first successful PyPI release, validate `server.pypi.json` with the MCP Registry and replace `server.json`
   as a separate operator action. The existing Windows MCPB entry remains active until then.

Local release check: install the `dev` extra, run `npm ci` in `frontend`, then
`python tools/build_wheel.py` and `python tools/smoke_wheel.py`. Artifacts go to ignored `dist-py/`.
