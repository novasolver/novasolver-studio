"""Exercise the built exe over MCP in a private workspace: models above the direct-solver limit, which need the bundled AMG
(a package missing from the bundle shows only here, never from source), Flash, and a surrogate build through the frozen
worker whose answers must scale as the physics says.

    python tools/smoke_exe.py build/dist/NovaSolverStudio/NovaSolverStudio.exe"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

sys.stdout.reconfigure(encoding="utf-8")
TIMEOUT_S = 1500
LARGE = ("cantilever", "cantilever-modal", "thermal-block")     # structural, eigenvalue and scalar solves at the fine mesh
EXPECTED_TOOLS = 37                                             # 35 + run_genesis, genesis_result


async def check(exe: str, folder: str) -> None:
    env = dict(os.environ, NOVASTUDIO_WORKSPACE=os.path.join(folder, "ws"), LOCALAPPDATA=os.path.join(folder, "lad"),
               NOVASTUDIO_MCP_NO_IMAGES="1")
    env.pop("PYTHONPATH", None)
    os.makedirs(env["LOCALAPPDATA"], exist_ok=True)
    async with stdio_client(StdioServerParameters(command=os.path.abspath(exe), args=["mcp"], env=env)) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = (await s.list_tools()).tools
            assert len(tools) == EXPECTED_TOOLS, len(tools)

            async def call(name, **kw):
                x = await s.call_tool(name, {**kw, "language": "en"})
                assert not x.is_error, (name, x.content[0].text)
                return x

            async def new_case(template, **changes):
                sc = (await call("create_case", template=template, changes=changes)).structured_content
                return sc.get("case_id") or sc["case"]["case_id"]

            for template in LARGE:
                t0 = time.time()
                done = await call("run_simulation", case_id=await new_case(template, **{"mesh.size": "fine"}), mode="preview")
                job = done.structured_content.get("job_id") or done.structured_content["job"]["job_id"]
                sc = done.structured_content
                while not sc.get("done") and sc.get("state") not in ("done", "failed", "stopped"):
                    sc = (await call("job_status", job_id=job)).structured_content
                    assert time.time() - t0 < TIMEOUT_S, template
                assert sc.get("done") or sc["state"] == "done", (template, sc)
                print(f"{template} fine mesh: solved in {time.time() - t0:.0f} s", flush=True)

            # Genesis through the frozen worker: half model (y), extrusion with its STEP (gmsh + contourpy in the
            # bundle), finishing pass
            t0 = time.time()
            gid = await new_case("cantilever")
            run = await call("run_genesis", case_id=gid, cells=6000, iterations=30, extrusion="y", symmetry=["y"], refine=True)
            sc = run.structured_content
            job = sc.get("job_id")
            while job and not sc.get("done") and sc.get("state") not in ("done", "failed", "stopped"):
                sc = (await call("job_status", job_id=job)).structured_content
                assert time.time() - t0 < TIMEOUT_S, "genesis"
                await asyncio.sleep(3)
            res = (await call("genesis_result", case_id=gid)).structured_content
            print(f"genesis: {time.time() - t0:.0f} s, refine: {res['refine']['message'][:80]}", flush=True)
            assert res["surface"]["closed"] and "step" in res["files"], res["files"]
            assert res.get("step") and res["step"].get("volume_m3", 0) > 0, res.get("step")

            flash = await call("instant_estimate", shape="plate_hole", ratios={"d_over_W": 0.3, "t_over_W": 0.2})
            print(flash.content[0].text[:200], flush=True)
            t0 = time.time()
            built = await call("build_surrogate", case_id=await new_case("cantilever"),
                               parameters=[{"path": "boundaries.x1.force", "min": 500, "max": 2000, "unit": "N"}], n=20, mesh_checks=1)
            sid = built.structured_content["study_id"]
            while True:
                st = await call("surrogate_status", study_id=sid)
                if st.structured_content["state"] in ("done", "failed", "interrupted"):
                    break
                assert time.time() - t0 < TIMEOUT_S, st.content[0].text
                await asyncio.sleep(5)
            print(st.content[0].text, flush=True)
            assert st.structured_content["state"] == "done"
            assert st.structured_content["model"]["mesh"]["gci_max_pct"] is not None   # the fine level solved
            answer = await call("surrogate_predict", study_id=sid, values={"boundaries.x1.force": 1000})
            print(answer.content[0].text, flush=True)
            assert "normal mesh" in answer.content[0].text
            study = os.path.join(env["NOVASTUDIO_WORKSPACE"], "surrogates", sid)
            with open(os.path.join(study, "study.json"), encoding="utf-8") as f:
                design = json.load(f)["design"]
            assert len({tuple(u) for u in design}) == len(design), "the design repeats points"
            with open(os.path.join(study, "worker.log"), encoding="utf-8", errors="replace") as f:
                log = f.read()
            assert "Traceback" not in log and "Exception ignored" not in log, log[-1500:]
            low, high = [(await call("surrogate_predict", study_id=sid, values={"boundaries.x1.force": v})).structured_content["results"]
                         for v in (500, 2000)]
            for a, b in zip(low, high):                                 # small-strain beam: four times the load, four times the answer
                assert abs(b["value"] / a["value"] / 4 - 1) < 0.02, (a, b)


def main() -> None:
    folder = tempfile.mkdtemp(prefix="nss_smoke_exe_")
    asyncio.run(check(sys.argv[1], folder))
    print("exe smoke test passed")


if __name__ == "__main__":
    main()
