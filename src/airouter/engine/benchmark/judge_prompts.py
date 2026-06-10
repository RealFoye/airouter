"""Task-type-specific rubrics for LLM Judge evaluation."""

from __future__ import annotations

# ── Dimension definitions per task_type ──────────────────────

_DIMENSIONS: dict[str, dict[str, float]] = {
    "CODE_GENERATION": {
        "correctness": 0.35,
        "code_quality": 0.25,
        "completeness": 0.20,
        "error_handling": 0.10,
        "performance": 0.10,
    },
    "CODE_REVIEW": {
        "issue_detection": 0.30,
        "fix_suggestion": 0.25,
        "severity_accuracy": 0.20,
        "completeness": 0.15,
        "practicality": 0.10,
    },
    "ARCHITECTURE": {
        "design_soundness": 0.30,
        "tradeoff_analysis": 0.25,
        "scalability": 0.20,
        "completeness": 0.15,
        "practicality": 0.10,
    },
    "REFACTORING": {
        "improvement_clarity": 0.30,
        "correctness": 0.25,
        "best_practices": 0.20,
        "completeness": 0.15,
        "maintainability": 0.10,
    },
    "BUG_ANALYSIS": {
        "root_cause_accuracy": 0.35,
        "fix_correctness": 0.30,
        "explanation": 0.20,
        "prevention": 0.15,
    },
    "DOCUMENTATION": {
        "accuracy": 0.30,
        "completeness": 0.25,
        "clarity": 0.20,
        "structure": 0.15,
        "examples": 0.10,
    },
    "FINANCE_DATA_PROCESSING": {
        "numeric_policy_correctness": 0.35,
        "evidence_grounding": 0.25,
        "hallucination_control": 0.20,
        "business_usability": 0.15,
        "json_structure_quality": 0.05,
    },
    "FINANCE_POLICY_QA": {
        "policy_accuracy": 0.30,
        "evidence_grounding": 0.25,
        "hallucination_control": 0.25,
        "business_usability": 0.10,
        "json_structure_quality": 0.10,
    },
}

# ── Fallback for unknown task_type ───────────────────────────

_DEFAULT_DIMENSIONS: dict[str, float] = {
    "correctness": 0.35,
    "completeness": 0.30,
    "practicality": 0.20,
    "depth": 0.15,
}

# ── Rubric text per dimension ────────────────────────────────

_RUBRIC_TEXT: dict[str, str] = {
    # CODE_GENERATION dimensions
    "correctness": (
        "正确性（correctness）：代码逻辑是否正确？能否处理边界情况？算法是否产生正确结果？\n"
        "- 1分：逻辑有根本性错误，无法运行\n"
        "- 2分：主体逻辑有bug，部分场景输出错误\n"
        "- 3分：基本正确，但有边界case未处理或小bug\n"
        "- 4分：逻辑正确，边界case处理良好\n"
        "- 5分：完全正确，所有case（含极端情况）均通过"
    ),
    "code_quality": (
        "代码质量（code_quality）：命名、结构、可读性如何？\n"
        "- 1分：变量命名混乱，无结构，无法阅读\n"
        "- 2分：命名不规范，结构松散，需要大量注释才能理解\n"
        "- 3分：基本可读，命名大致合理\n"
        "- 4分：命名清晰，结构良好，有类型提示和文档字符串\n"
        "- 5分：专业级代码质量，可直接用于生产"
    ),
    "completeness": (
        "完整性（completeness）：是否覆盖了任务要求的所有要点？\n"
        "- 1分：只完成了不到30%的要求\n"
        "- 2分：完成了30-60%，关键功能缺失\n"
        "- 3分：完成了60-90%，次要功能有遗漏\n"
        "- 4分：完成了90%以上，只有极小的遗漏\n"
        "- 5分：100%完成所有要求，超出预期"
    ),
    "error_handling": (
        "错误处理（error_handling）：异常处理是否完善？\n"
        "- 1分：完全没有错误处理\n"
        "- 2分：有try/except但过于宽泛（bare except）\n"
        "- 3分：主要异常有处理，但不够精确\n"
        "- 4分：精确的异常处理，有日志和恢复策略\n"
        "- 5分：完善的错误处理、重试、降级机制"
    ),
    "performance": (
        "性能（performance）：代码效率如何？\n"
        "- 1分：有明显性能问题（如O(n²)可优化为O(n)）\n"
        "- 2分：效率一般，有大量不必要的计算\n"
        "- 3分：基本合理，无明显浪费\n"
        "- 4分：高效实现，考虑了时间/空间复杂度\n"
        "- 5分：最优算法，有缓存/预处理等优化"
    ),
    # CODE_REVIEW dimensions
    "issue_detection": (
        "问题发现（issue_detection）：是否准确识别了代码中的问题？\n"
        "- 1分：未发现任何真实问题，或指出的都不是真正的问题\n"
        "- 2分：发现了部分问题，但遗漏了关键安全问题\n"
        "- 3分：发现了主要问题，但有遗漏\n"
        "- 4分：准确识别了所有重要问题\n"
        "- 5分：发现了所有问题，包括隐蔽的边界情况和潜在风险"
    ),
    "fix_suggestion": (
        "修复建议（fix_suggestion）：给出的修复方案是否正确可行？\n"
        "- 1分：没有给出修复建议，或建议是错误的\n"
        "- 2分：修复建议部分正确但有重大缺陷\n"
        "- 3分：修复建议基本正确，但不够具体\n"
        "- 4分：给出了具体可行的修复代码/方案\n"
        "- 5分：修复方案完善，考虑了副作用和兼容"
    ),
    "severity_accuracy": (
        "严重度判断（severity_accuracy）：问题的严重程度评估是否准确？\n"
        "- 1分：严重度判断完全错误\n"
        "- 2分：严重度判断有多处偏差\n"
        "- 3分：严重度判断大体正确\n"
        "- 4分：严重度评估准确，有合理的解释\n"
        "- 5分：精准评估，有数据/案例支撑严重度判断"
    ),
    # ARCHITECTURE dimensions
    "design_soundness": (
        "设计合理性（design_soundness）：架构设计是否合理？\n"
        "- 1分：设计有根本性缺陷，无法满足需求\n"
        "- 2分：设计有明显不合理之处\n"
        "- 3分：设计基本合理，但有不完善的地方\n"
        "- 4分：设计合理，组件职责清晰\n"
        "- 5分：设计优秀，考虑到各种场景和约束"
    ),
    "tradeoff_analysis": (
        "权衡分析（tradeoff_analysis）：是否分析了技术选型的利弊？\n"
        "- 1分：没有分析，直接给结论\n"
        "- 2分：简单罗列优缺点，没有分析\n"
        "- 3分：有基本的利弊分析\n"
        "- 4分：深入分析权衡，有适用场景说明\n"
        "- 5分：全面的权衡分析，有定量对比和决策依据"
    ),
    "scalability": (
        "可扩展性（scalability）：设计是否考虑了规模增长？\n"
        "- 1分：完全没有考虑扩展性\n"
        "- 2分：提到了扩展性但没有具体方案\n"
        "- 3分：有基本的扩展方案\n"
        "- 4分：详细的扩展策略，有容量规划\n"
        "- 5分：全面的可扩展设计，有水平/垂直扩展方案和瓶颈分析"
    ),
    # REFACTORING dimensions
    "improvement_clarity": (
        "改进清晰度（improvement_clarity）：重构后的代码是否明显更好？\n"
        "- 1分：重构后代码更差或没有改善\n"
        "- 2分：改善很小，不值得重构\n"
        "- 3分：有明显改善，但有些地方过度或不足\n"
        "- 4分：清晰的重构，每个改动都有明确目的\n"
        "- 5分：优雅的重构，代码质量显著提升"
    ),
    "best_practices": (
        "最佳实践（best_practices）：是否遵循了设计原则和最佳实践？\n"
        "- 1分：违反基本设计原则\n"
        "- 2分：部分遵循但不一致\n"
        "- 3分：基本遵循常见最佳实践\n"
        "- 4分：良好遵循SOLID/DRY等原则\n"
        "- 5分：完美应用设计模式和最佳实践"
    ),
    "maintainability": (
        "可维护性（maintainability）：重构后的代码是否易于维护？\n"
        "- 1分：代码难以理解和修改\n"
        "- 2分：维护性一般，需要大量上下文\n"
        "- 3分：基本可维护，结构清晰\n"
        "- 4分：良好的可维护性，有文档和测试\n"
        "- 5分：优秀的可维护性，模块化程度高"
    ),
    # BUG_ANALYSIS dimensions
    "root_cause_accuracy": (
        "根因准确性（root_cause_accuracy）：是否正确定位了问题的根本原因？\n"
        "- 1分：根因分析完全错误\n"
        "- 2分：找到了表面原因但不是根因\n"
        "- 3分：根因分析基本正确\n"
        "- 4分：准确定位根因，有清晰的因果链\n"
        "- 5分：精准定位根因，分析了深层原因和触发条件"
    ),
    "fix_correctness": (
        "修复正确性（fix_correctness）：提出的修复方案是否正确？\n"
        "- 1分：修复方案是错误的或会引入新问题\n"
        "- 2分：修复方案部分正确但不完整\n"
        "- 3分：修复方案基本正确\n"
        "- 4分：修复方案正确且完善\n"
        "- 5分：修复方案完美，考虑了兼容和回归风险"
    ),
    "explanation": (
        "解释清晰度（explanation）：问题分析是否清晰易懂？\n"
        "- 1分：解释混乱，无法理解\n"
        "- 2分：解释不够清晰，有歧义\n"
        "- 3分：解释基本清晰\n"
        "- 4分：解释清晰，有条理\n"
        "- 5分：解释优秀，有图表/代码辅助说明"
    ),
    "prevention": (
        "预防措施（prevention）：是否提出了防止问题复发的措施？\n"
        "- 1分：没有提出预防措施\n"
        "- 2分：预防措施不具体或不可行\n"
        "- 3分：有基本的预防措施\n"
        "- 4分：具体的预防措施（测试、监控、规范）\n"
        "- 5分：全面的预防方案，有系统性改进建议"
    ),
    # DOCUMENTATION dimensions
    "accuracy": (
        "准确性（accuracy）：文档内容是否准确？\n"
        "- 1分：包含事实性错误\n"
        "- 2分：有多处不准确的地方\n"
        "- 3分：基本准确，有小误差\n"
        "- 4分：准确可靠\n"
        "- 5分：完全准确，有权威来源支撑"
    ),
    "clarity": (
        "清晰度（clarity）：文档是否清晰易懂？\n"
        "- 1分：晦涩难懂\n"
        "- 2分：不够清晰，需要反复阅读\n"
        "- 3分：基本清晰\n"
        "- 4分：清晰易读，语言简洁\n"
        "- 5分：行文流畅，概念解释透彻"
    ),
    "structure": (
        "结构性（structure）：文档组织是否合理？\n"
        "- 1分：没有结构，内容混乱\n"
        "- 2分：有基本结构但组织不佳\n"
        "- 3分：结构合理\n"
        "- 4分：良好的章节划分和层次\n"
        "- 5分：优秀的文档结构，有目录、索引、交叉引用"
    ),
    "examples": (
        "示例质量（examples）：是否提供了有价值的示例？\n"
        "- 1分：没有示例\n"
        "- 2分：示例太少或不典型\n"
        "- 3分：有基本示例\n"
        "- 4分：示例丰富且实用\n"
        "- 5分：全面的示例，包括正常、异常、边界情况"
    ),
    # Default/fallback dimensions
    "depth": (
        "深度（depth）：分析是否有深度？\n"
        "- 1分：纯表面罗列，无分析\n"
        "- 2分：有浅层分析\n"
        "- 3分：有一定深度的分析\n"
        "- 4分：深入分析，有独到见解\n"
        "- 5分：非常深入，有系统性的思考和权衡"
    ),
    "practicality": (
        "实用性（practicality）：给出的方案在实际工程中能用吗？\n"
        "- 1分：完全脱离实际，无法使用\n"
        "- 2分：理论正确但实际很难用\n"
        "- 3分：基本能用，需要较多修改\n"
        "- 4分：实用，稍作调整即可使用\n"
        "- 5分：可直接用于生产环境"
    ),
    # FINANCE dimensions
    "numeric_policy_correctness": (
        "数值与政策正确性（numeric_policy_correctness）：金额计算、政策结论、Top-N 排序是否正确？\n"
        "- 1分：金额计算严重错误，政策结论完全错误\n"
        "- 2分：金额有多处错误，政策判断有明显偏差\n"
        "- 3分：金额基本正确（误差<5%），政策判断大体合理\n"
        "- 4分：金额精确（误差<1%），政策结论正确\n"
        "- 5分：金额完全精确，政策结论准确且有充分依据"
    ),
    "evidence_grounding": (
        "证据支撑（evidence_grounding）：回答是否严格基于题目提供的 CSV/制度/数据？\n"
        "- 1分：完全没有引用题目数据，凭空编造\n"
        "- 2分：引用了少量数据，但大部分结论无据可依\n"
        "- 3分：主要结论有数据支撑，但部分缺少引用\n"
        "- 4分：所有结论都有明确的数据引用和来源\n"
        "- 5分：精确引用具体行列/金额/条款，证据链完整"
    ),
    "hallucination_control": (
        "幻觉控制（hallucination_control）：是否避免了编造制度、数据、文件？\n"
        "- 1分：大量编造不存在的制度条款、数据或文件\n"
        "- 2分：有多处编造或臆断\n"
        "- 3分：有少量编造，但不影响主要结论\n"
        "- 4分：几乎无编造，所有信息都可追溯到源数据\n"
        "- 5分：零编造，对不确定的信息明确标注不确定性"
    ),
    "business_usability": (
        "业务可用性（business_usability）：财务人员能否直接使用这个结果？\n"
        "- 1分：输出格式混乱，无法用于业务决策\n"
        "- 2分：有部分可用信息，但需要大量人工整理\n"
        "- 3分：基本可用，但缺少关键业务上下文\n"
        "- 4分：结构清晰，结论明确，可直接用于决策\n"
        "- 5分：专业级输出，包含行动建议、风险提示和完整分析"
    ),
    "json_structure_quality": (
        "JSON 结构质量（json_structure_quality）：输出是否机器可读、结构规范？\n"
        "- 1分：无法解析为 JSON\n"
        "- 2分：可解析但结构混乱，字段命名不规范\n"
        "- 3分：基本结构化，但缺少必要字段或嵌套不当\n"
        "- 4分：结构清晰，字段命名合理，符合预期格式\n"
        "- 5分：完美的 JSON 结构，有类型一致性，易于程序化处理"
    ),
    "policy_accuracy": (
        "制度准确性（policy_accuracy）：对财务制度的理解和应用是否正确？\n"
        "- 1分：对制度的理解完全错误\n"
        "- 2分：部分正确但有重大误解\n"
        "- 3分：基本正确理解了制度要求\n"
        "- 4分：准确理解并正确应用了制度条款\n"
        "- 5分：精准应用制度，考虑了边界情况和例外条款"
    ),
}


def get_dimensions(task_type: str) -> dict[str, float]:
    """Return {dimension_name: weight} mapping for a task type."""
    return _DIMENSIONS.get(task_type, _DEFAULT_DIMENSIONS)


def get_rubric(task_type: str) -> str:
    """Return the full rubric text for a task type."""
    dims = get_dimensions(task_type)
    lines = [f"请从以下 {len(dims)} 个维度评分（1-5 分）："]
    for i, (dim_name, weight) in enumerate(dims.items(), 1):
        rubric = _RUBRIC_TEXT.get(dim_name, f"{dim_name}（权重 {weight}）")
        lines.append(f"{i}. {rubric}")
    lines.append("")
    lines.append("评分标准：")
    lines.append("- 1 分：完全不达标")
    lines.append("- 2 分：有明显不足")
    lines.append("- 3 分：基本达标，有小问题")
    lines.append("- 4 分：良好，质量较高")
    lines.append("- 5 分：优秀，可直接用于生产")
    return "\n".join(lines)


def get_json_format(task_type: str) -> str:
    """Return the expected JSON output format for a task type."""
    dims = get_dimensions(task_type)
    keys = ", ".join(f'"{k}": 分数' for k in dims)
    return f'{{{keys}, "comment": "一句话评语"}}'


# ── Finance-specific red flags and JSON format ───────────────

VALID_RED_FLAGS = frozenset({
    "hallucinated_policy",     # 编造不存在的制度条款
    "hallucinated_data",       # 编造数据/金额
    "weak_evidence",           # evidence 未引用实际附件
    "missing_source",          # 未引用题目提供的数据源
    "wrong_amount_reasoning",  # 金额计算推理有误
    "overconfident_uncertain", # 对不确定结论过于自信
    "json_structure_issue",    # JSON 结构不符合要求
    "business_action_unclear", # 业务建议/结论不清晰
})

_FINANCE_CATEGORY_NAMES = {
    "TABLE_CALCULATION": "表格计算",
    "REIMBURSEMENT_AUDIT": "报销审核",
    "THREE_WAY_MATCH": "三单匹配",
    "BANK_RECONCILIATION": "银行对账",
    "BUDGET_ANALYSIS": "预算分析",
    "POLICY_QA": "制度问答",
}


def get_finance_judge_task_type(category: str) -> str:
    """Map finance category to judge task type."""
    if category == "POLICY_QA":
        return "FINANCE_POLICY_QA"
    return "FINANCE_DATA_PROCESSING"


def get_finance_json_format(task_type: str) -> str:
    """Return the expected JSON output format for finance judge."""
    dims = get_dimensions(task_type)
    keys = ", ".join(f'"{k}": 分数' for k in dims)
    valid_flags = ", ".join(f'"{f}"' for f in sorted(VALID_RED_FLAGS))
    return (
        f'{{{keys}, '
        f'"rule_score_disagreement": "agree|rule_too_high|rule_too_low|unclear", '
        f'"red_flags": [可选值: {valid_flags}], '
        f'"comment": "中文简评"}}'
    )


def get_finance_category_name(category: str) -> str:
    """Return Chinese name for a finance category."""
    return _FINANCE_CATEGORY_NAMES.get(category, category)


def calculate_weighted_score(task_type: str, scores: dict[str, float]) -> float:
    """Calculate weighted overall score from dimension scores."""
    dims = get_dimensions(task_type)
    total = 0.0
    for dim, weight in dims.items():
        total += scores.get(dim, 0) * weight
    return total
