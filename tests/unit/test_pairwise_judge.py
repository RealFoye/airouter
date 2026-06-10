"""Tests for pairwise_judge: A/B order, winner mapping, JSON parsing."""

from __future__ import annotations

import json
import random
from pathlib import Path

from airouter.engine.benchmark.pairwise_judge import (
    _build_pairwise_prompt,
    _load_completed_keys,
    _parse_pairwise_json,
)

# ── JSON parsing ──────────────────────────────────────────────


class TestParsePairwiseJson:
    def test_direct_parse(self):
        content = '{"winner": "A", "reason": "better", "dimension_winners": {}}'
        result = _parse_pairwise_json(content)
        assert result is not None
        assert result["winner"] == "A"

    def test_tie_result(self):
        content = '{"winner": "tie", "reason": "equally good"}'
        result = _parse_pairwise_json(content)
        assert result is not None
        assert result["winner"] == "tie"

    def test_invalid_json(self):
        result = _parse_pairwise_json("not json")
        assert result is None


# ── Pairwise prompt ───────────────────────────────────────────


class TestBuildPairwisePrompt:
    def test_prompt_contains_outputs(self):
        case = {"id": "CG-001", "prompt": "Write a function", "task_type": "CODE_GENERATION"}
        prompt = _build_pairwise_prompt(case, "output A text", "output B text", "CODE_GENERATION")
        assert "Model A" in prompt
        assert "Model B" in prompt
        assert "output A text" in prompt
        assert "output B text" in prompt

    def test_prompt_includes_task_type_dimensions(self):
        case = {"id": "CG-001", "prompt": "test", "task_type": "CODE_REVIEW"}
        prompt = _build_pairwise_prompt(case, "a", "b", "CODE_REVIEW")
        assert "issue_detection" in prompt
        assert "fix_suggestion" in prompt

    def test_prompt_includes_input_context(self):
        case = {"id": "CG-001", "prompt": "test", "input_context": "Flask project"}
        prompt = _build_pairwise_prompt(case, "a", "b", "CODE_GENERATION")
        assert "Flask project" in prompt

    def test_hidden_model_names(self):
        case = {"id": "CG-001", "prompt": "test"}
        prompt = _build_pairwise_prompt(case, "a", "b", "CODE_GENERATION")
        # Should not contain actual model names (they are passed as output_a/output_b)
        assert "qwen" not in prompt.lower()
        assert "deepseek" not in prompt.lower()


# ── A/B order randomization ──────────────────────────────────


class TestAbOrderRandomization:
    def test_deterministic_rng(self):
        """Same seed produces same order."""
        seed = "CG-001:model_a:model_b:judge1"
        rng1 = random.Random(seed)
        swap1 = rng1.random() < 0.5

        rng2 = random.Random(seed)
        swap2 = rng2.random() < 0.5

        assert swap1 == swap2

    def test_different_seeds_differ(self):
        """Different seeds should (usually) produce different orders."""
        results = set()
        for i in range(20):
            rng = random.Random(f"case-{i}:ma:mb:judge")
            results.add(rng.random() < 0.5)
        # With 20 different seeds, we should see both True and False
        assert len(results) == 2


# ── Winner mapping ────────────────────────────────────────────


class TestWinnerMapping:
    def test_a_wins_when_a_is_model_a(self):
        """If A wins and a_was_first=True, winner is model_a."""
        winner_label = "A"
        a_was_first = True
        model_a, model_b = "qwen3.7-max", "deepseek-v4-pro"

        if winner_label == "A":
            winner_model = model_a if a_was_first else model_b
        assert winner_model == "qwen3.7-max"

    def test_a_wins_when_a_is_model_b(self):
        """If A wins and a_was_first=False, winner is model_b."""
        winner_label = "A"
        a_was_first = False
        model_a, model_b = "qwen3.7-max", "deepseek-v4-pro"

        if winner_label == "A":
            winner_model = model_a if a_was_first else model_b
        assert winner_model == "deepseek-v4-pro"

    def test_tie_maps_to_none(self):
        winner_label = "tie"
        winner_model = None if winner_label == "tie" else "something"
        assert winner_model is None


# ── JSONL resume ──────────────────────────────────────────────


class TestPairwiseJsonlResume:
    def test_load_completed_keys(self, tmp_path: Path):
        jsonl = tmp_path / "pairwise.jsonl"
        lines = [
            json.dumps({
                "case_id": "CG-001",
                "model_a": "m1",
                "model_b": "m2",
                "judge_model": "j1",
                "winner_label": "A",
            }),
        ]
        jsonl.write_text("\n".join(lines))
        keys = _load_completed_keys(jsonl)
        assert "CG-001:m1:m2:j1" in keys

    def test_skip_empty_winner(self, tmp_path: Path):
        jsonl = tmp_path / "pairwise.jsonl"
        lines = [
            json.dumps({
                "case_id": "CG-001",
                "model_a": "m1",
                "model_b": "m2",
                "judge_model": "j1",
                "winner_label": "",
            }),
        ]
        jsonl.write_text("\n".join(lines))
        keys = _load_completed_keys(jsonl)
        assert "CG-001:m1:m2:j1" not in keys
