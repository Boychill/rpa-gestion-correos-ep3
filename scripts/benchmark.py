"""Capacidad sintética medida; nunca envía ni usa Graph. Estado aislado por tamaño."""
from dataclasses import replace
import json
from pathlib import Path
import platform
import sys
import tempfile
import tracemalloc
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rpa.config import Settings
from rpa.orchestrator import run
from rpa.store import utcnow


def main():
    results = []
    for count in (100, 300, 500, 1000):
        with tempfile.TemporaryDirectory(prefix="rpa benchmark ") as directory:
            base = Path(directory)
            settings = Settings(root=ROOT, runtime=base / "runtime", output=base / "output", fixture_count=count)
            tracemalloc.start()
            timer = time.perf_counter()
            result = run(settings)
            elapsed = time.perf_counter()-timer
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            assert result["status"] == "COMPLETED", result
            assert result["metrics"]["classified"] == count
            assert result["send_state"] == "DRY_RUN"
            results.append(dict(count=count, seconds=round(elapsed, 4), throughput=round(count/elapsed, 2),
                                python_peak_bytes=peak, metrics=result["metrics"], status=result["status"]))
            print(json.dumps(results[-1]))
    evidence = {"source": "FIXTURE", "measured_at": utcnow(), "platform": platform.platform(),
                "python": platform.python_version(), "cpu": platform.processor(), "batch_size": 100,
                "page_size": 100, "memory_note": "tracemalloc: asignaciones Python; no es pico RSS ni memoria Office",
                "results": results}
    target = ROOT / "docs/evidence/benchmark.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
