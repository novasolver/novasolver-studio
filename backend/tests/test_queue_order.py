"""The machine-wide solver slot is first come, first served (a waiting job must not lose every race)."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
HOLD = """
import json, sys, time
from pathlib import Path
from novastudio import run_worker
jd = Path(sys.argv[1])
slot = run_worker._acquire_solver_slot(jd)
with open(sys.argv[2], 'a') as fh:
    fh.write(jd.name + '\\n')
time.sleep(float(sys.argv[3]))
run_worker._release_solver_slot(slot)
"""


def test_waiters_take_the_slot_in_arrival_order(tmp_path):
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path / "data"), PYTHONPATH=str(BACKEND))
    order = tmp_path / "order.txt"
    procs = []
    for i, hold in enumerate((3.0, 0.5, 0.5, 0.5)):
        jd = tmp_path / f"r_job_{i}"
        jd.mkdir()
        (jd / "job.json").write_text(json.dumps({"job_id": jd.name, "state": "queued", "created_at": time.time()}))
        procs.append(subprocess.Popen([sys.executable, "-c", HOLD, str(jd), str(order), str(hold)], env=env))
        time.sleep(0.6)                      # arrive one after another while job 0 holds the slot
    for p in procs:
        assert p.wait(60) == 0
    assert order.read_text().split() == [f"r_job_{i}" for i in range(4)]
    assert not list((tmp_path / "data" / "NovaSolverStudio" / "solver.queue").glob("*.json"))
