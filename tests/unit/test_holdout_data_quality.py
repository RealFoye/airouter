"""Holdout 数据质量测试：无重复 prompt、真值合理、CODE_DEBUG 完整性。"""

from __future__ import annotations

import pytest

from airouter.engine.benchmark.ground_truth_loader import load_holdout_cases
from airouter.engine.benchmark.ground_truth_schemas import (
    VALID_HOLDOUT_CATEGORIES,
    GroundTruthCase,
)


@pytest.fixture(scope="module")
def holdout_cases() -> list[GroundTruthCase]:
    return load_holdout_cases()


class TestHoldoutDataQuality:
    def test_no_duplicate_prompts(self, holdout_cases):
        prompts = [c.prompt for c in holdout_cases]
        assert len(prompts) == len(set(prompts)), "duplicate prompts found"

    def test_no_placeholder_content(self, holdout_cases):
        """禁止占位内容（'这是一个测试文档'、'function_N' 等）。"""
        placeholders = [
            "这是一个测试文档", "function_", "问题N",
            "回复N", "分析文档",
        ]
        for c in holdout_cases:
            for ph in placeholders:
                assert ph not in c.prompt, f"{c.id}: placeholder '{ph}' in prompt"
                assert ph not in c.input_context, f"{c.id}: placeholder '{ph}' in input_context"

    def test_all_categories_represented(self, holdout_cases):
        categories = {c.category for c in holdout_cases}
        for vc in VALID_HOLDOUT_CATEGORIES:
            assert vc in categories, f"missing category: {vc}"

    def test_code_debug_has_workspace_and_tests(self, holdout_cases):
        """CODE_DEBUG 必须有 workspace_files + test_files + harness_validation。"""
        code_debug = [c for c in holdout_cases if c.category == "CODE_DEBUG"]
        assert len(code_debug) > 0, "no CODE_DEBUG cases"
        for c in code_debug:
            assert c.workspace_files, f"{c.id}: missing workspace_files"
            assert c.ground_truth.test_files, f"{c.id}: missing test_files"
            assert c.harness_validation.commands, f"{c.id}: missing harness commands"

    def test_should_ask_clarification_coverage(self, holdout_cases):
        """至少 5 个 case 设置 should_ask_clarification=true。"""
        clarify = [c for c in holdout_cases if c.evaluation.should_ask_clarification]
        assert len(clarify) >= 5, (
            f"only {len(clarify)} cases with should_ask_clarification (need >= 5)"
        )

    def test_case_count(self, holdout_cases):
        """Holdout 应有 60 个 cases。"""
        assert len(holdout_cases) == 60, f"expected 60 cases, got {len(holdout_cases)}"

    def test_all_domains_general(self, holdout_cases):
        """所有 holdout cases domain 应为 GENERAL。"""
        for c in holdout_cases:
            assert c.domain == "GENERAL", f"{c.id}: domain={c.domain}"

    def test_no_empty_prompts(self, holdout_cases):
        for c in holdout_cases:
            assert c.prompt.strip(), f"{c.id}: empty prompt"

    def test_table_data_has_expected_values(self, holdout_cases):
        """TABLE_DATA cases 应有 expected_values 用于确定性验证。"""
        table_cases = [c for c in holdout_cases if c.category == "TABLE_DATA"]
        assert len(table_cases) > 0
        for c in table_cases:
            assert c.ground_truth.expected_values, (
                f"{c.id}: TABLE_DATA missing expected_values"
            )

    def test_multi_turn_has_history(self, holdout_cases):
        """MULTI_TURN cases 应有 history_messages。"""
        mt_cases = [c for c in holdout_cases if c.category == "MULTI_TURN"]
        assert len(mt_cases) > 0
        for c in mt_cases:
            assert c.routing_metadata.history_messages, (
                f"{c.id}: MULTI_TURN missing history_messages"
            )
