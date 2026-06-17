"""验证 Holdout 数据质量：无重复 prompt、真值算术正确、CODE_DEBUG 完整性。

用法：python scripts/validate_holdout_cases.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from airouter.engine.benchmark.ground_truth_loader import load_holdout_cases
from airouter.engine.benchmark.ground_truth_schemas import VALID_HOLDOUT_CATEGORIES


def validate() -> list[str]:
    errors: list[str] = []

    try:
        cases = load_holdout_cases()
    except Exception as e:
        return [f"加载失败: {e}"]

    if len(cases) == 0:
        errors.append("无 holdout cases")
        return errors

    # 1. 无重复 prompt
    prompts = [c.prompt for c in cases]
    seen = set()
    for i, p in enumerate(prompts):
        if p in seen:
            errors.append(f"duplicate prompt at case {cases[i].id}: {p[:60]}...")
        seen.add(p)

    # 2. 无占位内容
    placeholders = [
        "这是一个测试文档", "测试文档", "function_", "问题N",
        "回复N", "分析文档", "分析销售数据表", "修复代码片段",
        "分析系统日志", "任务N", "制定项目", "回答问题",
    ]
    for c in cases:
        for ph in placeholders:
            if ph in c.prompt or ph in c.input_context:
                errors.append(f"{c.id}: placeholder text '{ph}' found")
                break

    # 3. TABLE_DATA 数值真值验证
    for c in cases:
        if c.category == "TABLE_DATA" and c.ground_truth.expected_values:
            ev = c.ground_truth.expected_values
            if "total_sales" in ev:
                # 基本合理性检查
                total = ev["total_sales"]
                if total <= 0:
                    errors.append(f"{c.id}: total_sales={total} is non-positive")
                if total > 1000000:
                    errors.append(f"{c.id}: total_sales={total} seems unreasonably large")

    # 4. CODE_DEBUG 完整性
    for c in cases:
        if c.category == "CODE_DEBUG":
            if not c.workspace_files:
                errors.append(f"{c.id}: CODE_DEBUG missing workspace_files")
            if not c.harness_validation or not c.harness_validation.commands:
                errors.append(f"{c.id}: CODE_DEBUG missing harness_validation.commands")
            if not c.ground_truth.test_files:
                errors.append(f"{c.id}: CODE_DEBUG missing ground_truth.test_files")

    # 5. should_ask_clarification 覆盖
    clarify_cases = [c for c in cases if c.evaluation.should_ask_clarification]
    if len(clarify_cases) < 5:
        errors.append(
            f"only {len(clarify_cases)} cases with should_ask_clarification (need >= 5)"
        )

    # 6. 所有必填字段
    for c in cases:
        if not c.prompt:
            errors.append(f"{c.id}: empty prompt")
        if not c.category:
            errors.append(f"{c.id}: empty category")
        if c.category not in VALID_HOLDOUT_CATEGORIES:
            errors.append(f"{c.id}: invalid category '{c.category}'")
        if not c.id:
            errors.append("case with empty id")

    # 7. 类别覆盖
    categories = {c.category for c in cases}
    for vc in VALID_HOLDOUT_CATEGORIES:
        if vc not in categories:
            errors.append(f"missing category: {vc}")

    # 8. domain 一致性
    for c in cases:
        if c.domain != "GENERAL":
            errors.append(f"{c.id}: holdout case domain should be GENERAL, got {c.domain}")

    return errors


def main() -> int:
    errors = validate()
    if errors:
        print(f"FAILED: {len(errors)} errors")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: all holdout cases pass validation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
