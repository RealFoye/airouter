"""恢复 demo 场景到初始状态（把 .bak 文件还原）。"""

import shutil
from pathlib import Path

DEMO_DIR = Path(__file__).parent


def reset_scenario(scenario_dir: Path) -> None:
    """恢复单个场景的 .bak 文件。"""
    count = 0
    for bak in sorted(scenario_dir.rglob("*.bak")):
        original = bak.with_suffix("")  # auth.py.bak → auth.py
        shutil.copy2(bak, original)
        print(f"  restored: {original.relative_to(DEMO_DIR)}")
        count += 1
    if count == 0:
        print("  (no .bak files found)")


def main() -> None:
    """恢复所有 demo 场景。"""
    for d in sorted(DEMO_DIR.iterdir()):
        if d.is_dir() and d.name.startswith("scenario"):
            print(f"Resetting {d.name}...")
            reset_scenario(d)
    print("\nDone. All scenarios restored to initial state.")


if __name__ == "__main__":
    main()
