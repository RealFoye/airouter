"""Web 数据层测试。"""

from __future__ import annotations

import json
from pathlib import Path

from airouter.web.data import current_routing_progress, read_jsonl


def test_read_jsonl_skips_partial_last_line(tmp_path: Path) -> None:
    path = tmp_path / "results.jsonl"
    path.write_text('{"id": 1}\n{"id": 2}\n{"id":', encoding="utf-8")
    assert read_jsonl(path) == [{"id": 1}, {"id": 2}]


def test_current_routing_progress_dedupes_last_entry(tmp_path: Path) -> None:
    run_dir = tmp_path / "20260615_000000"
    run_dir.mkdir()
    rows = [
        {"case_id": "A", "model": "m1", "run_index": 0, "status": "failed"},
        {
            "case_id": "A",
            "model": "m1",
            "run_index": 0,
            "status": "success",
            "estimated_cost_cny": 0.1,
        },
        {
            "case_id": "A",
            "model": "m2",
            "run_index": 0,
            "status": "success",
            "estimated_cost_cny": 0.2,
        },
    ]
    (run_dir / "results.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    progress = current_routing_progress(tmp_path)
    assert progress is not None
    assert progress.completed == 2
    assert progress.succeeded == 2
    assert progress.failed == 0
    assert progress.cost_cny == 0.3

