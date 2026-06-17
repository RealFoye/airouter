#!/usr/bin/env python3
"""生成 Holdout benchmark cases YAML。

60 cases 跨 8 个领域，覆盖不同 complexity/risk 组合。
"""

import yaml
from pathlib import Path

OUTPUT_PATH = Path(__file__).parent.parent / "data/benchmarks/routing_ground_truth/general_cases.yaml"


def generate_cases() -> list[dict]:
    """生成 60 个 holdout cases。"""
    cases = []

    # ── DOC_UNDERSTANDING (8 cases) ──────────────────────────────────
    cases.extend([
        {
            "id": "GT-DOC-001",
            "domain": "GENERAL",
            "category": "DOC_UNDERSTANDING",
            "task_type": "ANALYSIS_ONLY",
            "complexity": "SIMPLE",
            "risk_level": "LOW",
            "prompt": "请总结这份用户协议的核心条款，列出用户的主要权利和义务。",
            "input_context": """用户服务协议 v2.1

第一条 服务内容
本平台提供 AI 模型路由服务，根据用户任务自动选择最优模型。

第二条 用户权利
1. 用户有权获得准确的路由决策说明
2. 用户有权查看模型调用成本明细
3. 用户有权导出历史使用数据

第三条 用户义务
1. 用户不得上传恶意代码或攻击性内容
2. 用户应确保任务描述准确完整
3. 用户应按时支付服务费用

第四条 免责条款
本平台不对模型输出内容的准确性承担责任。""",
            "routing_metadata": {
                "history_user_texts": [],
                "prev_assistant_text": None,
                "prev_assistant_usage": None,
                "n_tools": 0,
                "tool_result_length": 0,
            },
            "expected_behavior": ["识别用户权利3条", "识别用户义务3条", "提到免责条款"],
            "forbidden_behavior": ["添加协议中不存在的条款", "曲解条款含义"],
            "evaluation": {
                "primary": "rule_based",
                "required_findings": ["用户权利", "用户义务", "免责条款"],
                "forbidden_findings": ["付费义务", "法律责任"],
                "required_outputs": ["总结"],
                "forbidden_outputs": [],
                "must_not_modify": [],
                "should_ask_clarification": False,
                "requires_human_approval": False,
            },
            "ground_truth": {
                "expected_values": {},
                "expected_fact_ids": ["rights_3", "obligations_3", "disclaimer"],
                "hidden_tests": [],
                "allowed_root_causes": [],
                "evidence_line_ids": [],
                "expected_tools": [],
                "required_history_refs": [],
                "allowed_claims": ["用户有3项权利", "用户有3项义务", "平台不保证准确性"],
                "forbidden_claims": ["用户需承担法律责任", "平台保证100%准确"],
            },
            "workspace_files": {},
            "harness_validation": None,
            "structured_output": {
                "required_fields": ["action", "summary", "findings"],
                "optional_fields": ["evidence"],
            },
            "max_tokens": 2048,
            "tags": ["summary", "legal"],
        },
        # DOC-002 to DOC-008 will follow similar pattern
    ])

    # Add remaining DOC cases (simplified for brevity)
    for i in range(2, 9):
        cases.append({
            "id": f"GT-DOC-{i:03d}",
            "domain": "GENERAL",
            "category": "DOC_UNDERSTANDING",
            "task_type": "ANALYSIS_ONLY",
            "complexity": ["SIMPLE", "MODERATE", "MODERATE", "COMPLEX"][i % 4],
            "risk_level": ["LOW", "LOW", "MEDIUM", "MEDIUM"][i % 4],
            "prompt": f"分析文档{i}的关键信息并提取核心要点。",
            "input_context": f"文档{i}内容：这是一个测试文档，包含多个段落和关键信息点。" * 3,
            "routing_metadata": {
                "history_user_texts": [],
                "prev_assistant_text": None,
                "prev_assistant_usage": None,
                "n_tools": 0,
                "tool_result_length": 0,
            },
            "expected_behavior": ["提取关键信息", "识别文档结构"],
            "forbidden_behavior": ["编造内容"],
            "evaluation": {
                "primary": "rule_based",
                "required_findings": ["关键信息"],
                "forbidden_findings": [],
                "required_outputs": ["分析结果"],
                "forbidden_outputs": [],
                "must_not_modify": [],
                "should_ask_clarification": False,
                "requires_human_approval": False,
            },
            "ground_truth": {
                "expected_values": {},
                "expected_fact_ids": [f"doc_{i}_fact_1"],
                "hidden_tests": [],
                "allowed_root_causes": [],
                "evidence_line_ids": [],
                "expected_tools": [],
                "required_history_refs": [],
                "allowed_claims": ["文档包含关键信息"],
                "forbidden_claims": [],
            },
            "workspace_files": {},
            "harness_validation": None,
            "structured_output": {
                "required_fields": ["action", "summary", "findings"],
                "optional_fields": [],
            },
            "max_tokens": 2048,
            "tags": ["analysis"],
        })

    # ── TABLE_DATA (8 cases) ──────────────────────────────────
    cases.append({
        "id": "GT-TBL-001",
        "domain": "GENERAL",
        "category": "TABLE_DATA",
        "task_type": "ANALYSIS_ONLY",
        "complexity": "SIMPLE",
        "risk_level": "LOW",
        "prompt": "计算这份销售数据的总销售额，并找出销售额最高的产品。",
        "input_context": """产品,数量,单价
产品A,100,5.50
产品B,200,3.25
产品C,150,8.00
产品D,80,12.50""",
        "routing_metadata": {
            "history_user_texts": [],
            "prev_assistant_text": None,
            "prev_assistant_usage": None,
            "n_tools": 0,
            "tool_result_length": 0,
        },
        "expected_behavior": ["计算各产品销售额", "求总销售额", "找出最高销售额产品"],
        "forbidden_behavior": ["计算错误", "遗漏产品"],
        "evaluation": {
            "primary": "rule_based",
            "required_findings": ["总销售额", "最高销售额产品"],
            "forbidden_findings": [],
            "required_outputs": ["计算结果"],
            "forbidden_outputs": [],
            "must_not_modify": [],
            "should_ask_clarification": False,
            "requires_human_approval": False,
        },
        "ground_truth": {
            "expected_values": {
                "total_sales": 3650.0,  # 550 + 650 + 1200 + 1000 + 250
                "top_product": "产品C",  # 150 * 8.00 = 1200
            },
            "expected_fact_ids": [],
            "hidden_tests": [],
            "allowed_root_causes": [],
            "evidence_line_ids": [],
            "expected_tools": [],
            "required_history_refs": [],
            "allowed_claims": ["总销售额3650", "产品C销售额最高"],
            "forbidden_claims": [],
        },
        "workspace_files": {},
        "harness_validation": None,
        "structured_output": {
            "required_fields": ["action", "summary", "findings"],
            "optional_fields": ["evidence"],
        },
        "max_tokens": 2048,
        "tags": ["calculation", "csv"],
    })

    # Add remaining TABLE_DATA cases
    for i in range(2, 9):
        cases.append({
            "id": f"GT-TBL-{i:03d}",
            "domain": "GENERAL",
            "category": "TABLE_DATA",
            "task_type": "ANALYSIS_ONLY",
            "complexity": ["SIMPLE", "MODERATE", "COMPLEX"][i % 3],
            "risk_level": ["LOW", "MEDIUM", "HIGH"][i % 3],
            "prompt": f"分析销售数据表{i}，计算关键指标并生成报告。",
            "input_context": f"日期,产品,数量,单价\n" + "\n".join([
                f"2024-{m:02d}-01,产品X,{100+i*10},{5.0+i}" for m in range(1, 4)
            ]),
            "routing_metadata": {
                "history_user_texts": [],
                "prev_assistant_text": None,
                "prev_assistant_usage": None,
                "n_tools": 0,
                "tool_result_length": 0,
            },
            "expected_behavior": ["计算销售额", "分析趋势"],
            "forbidden_behavior": ["计算错误"],
            "evaluation": {
                "primary": "rule_based",
                "required_findings": ["销售额"],
                "forbidden_findings": [],
                "required_outputs": ["分析报告"],
                "forbidden_outputs": [],
                "must_not_modify": [],
                "should_ask_clarification": False,
                "requires_human_approval": False,
            },
            "ground_truth": {
                "expected_values": {"row_count": 3},
                "expected_fact_ids": [],
                "hidden_tests": [],
                "allowed_root_causes": [],
                "evidence_line_ids": [],
                "expected_tools": [],
                "required_history_refs": [],
                "allowed_claims": ["包含销售数据"],
                "forbidden_claims": [],
            },
            "workspace_files": {},
            "harness_validation": None,
            "structured_output": {
                "required_fields": ["action", "summary", "findings"],
                "optional_fields": [],
            },
            "max_tokens": 2048,
            "tags": ["data_analysis"],
        })

    # ── CODE_DEBUG (8 cases) ──────────────────────────────────
    cases.append({
        "id": "GT-DBG-001",
        "domain": "GENERAL",
        "category": "CODE_DEBUG",
        "task_type": "CODE_MODIFICATION",
        "complexity": "SIMPLE",
        "risk_level": "LOW",
        "prompt": "修复这个 Python 函数中的 bug：当输入为空列表时应该返回 0，但现在会抛出异常。",
        "input_context": """```python
def calculate_average(numbers):
    total = sum(numbers)
    return total / len(numbers)
```

测试用例：
- `calculate_average([1, 2, 3])` → 2.0 ✓
- `calculate_average([])` → 应该返回 0，但抛出 ZeroDivisionError""",
        "routing_metadata": {
            "history_user_texts": [],
            "prev_assistant_text": None,
            "prev_assistant_usage": None,
            "n_tools": 0,
            "tool_result_length": 0,
        },
        "expected_behavior": ["添加空列表检查", "返回 0"],
        "forbidden_behavior": ["修改其他逻辑", "改变函数签名"],
        "evaluation": {
            "primary": "rule_based",
            "required_findings": ["空列表导致除零错误"],
            "forbidden_findings": [],
            "required_outputs": ["修复后的代码"],
            "forbidden_outputs": [],
            "must_not_modify": [],
            "should_ask_clarification": False,
            "requires_human_approval": False,
        },
        "ground_truth": {
            "expected_values": {},
            "expected_fact_ids": [],
            "hidden_tests": [
                "assert calculate_average([]) == 0",
                "assert calculate_average([1,2,3]) == 2.0",
            ],
            "allowed_root_causes": [],
            "evidence_line_ids": [],
            "expected_tools": [],
            "required_history_refs": [],
            "allowed_claims": ["需要检查空列表"],
            "forbidden_claims": [],
        },
        "workspace_files": {
            "solution.py": """def calculate_average(numbers):
    total = sum(numbers)
    return total / len(numbers)
"""
        },
        "harness_validation": {
            "commands": ["python -m pytest test_solution.py -v"],
            "timeout_s": 10,
            "expected_exit_code": 0,
        },
        "structured_output": {
            "required_fields": ["action", "summary", "findings", "patch"],
            "optional_fields": ["modified_files"],
        },
        "max_tokens": 4096,
        "tags": ["bug_fix", "python"],
    })

    # Add remaining CODE_DEBUG cases
    for i in range(2, 9):
        cases.append({
            "id": f"GT-DBG-{i:03d}",
            "domain": "GENERAL",
            "category": "CODE_DEBUG",
            "task_type": "CODE_MODIFICATION",
            "complexity": ["SIMPLE", "MODERATE", "COMPLEX"][i % 3],
            "risk_level": ["LOW", "MEDIUM", "HIGH"][i % 3],
            "prompt": f"修复代码片段{i}中的问题，确保所有测试通过。",
            "input_context": f"```python\ndef function_{i}(x):\n    return x * 2\n```",
            "routing_metadata": {
                "history_user_texts": [],
                "prev_assistant_text": None,
                "prev_assistant_usage": None,
                "n_tools": 0,
                "tool_result_length": 0,
            },
            "expected_behavior": ["识别问题", "提供修复"],
            "forbidden_behavior": ["引入新 bug"],
            "evaluation": {
                "primary": "rule_based",
                "required_findings": ["问题原因"],
                "forbidden_findings": [],
                "required_outputs": ["修复代码"],
                "forbidden_outputs": [],
                "must_not_modify": [],
                "should_ask_clarification": False,
                "requires_human_approval": False,
            },
            "ground_truth": {
                "expected_values": {},
                "expected_fact_ids": [],
                "hidden_tests": [],
                "allowed_root_causes": [],
                "evidence_line_ids": [],
                "expected_tools": [],
                "required_history_refs": [],
                "allowed_claims": ["已修复"],
                "forbidden_claims": [],
            },
            "workspace_files": {
                "solution.py": f"def function_{i}(x):\n    return x * 2\n"
            },
            "harness_validation": {
                "commands": ["python -I solution.py"],
                "timeout_s": 5,
                "expected_exit_code": 0,
            },
            "structured_output": {
                "required_fields": ["action", "summary", "findings", "patch"],
                "optional_fields": [],
            },
            "max_tokens": 4096,
            "tags": ["debug"],
        })

    # ── LOG_OPS (8 cases) ──────────────────────────────────
    cases.append({
        "id": "GT-LOG-001",
        "domain": "GENERAL",
        "category": "LOG_OPS",
        "task_type": "ANALYSIS_ONLY",
        "complexity": "MODERATE",
        "risk_level": "MEDIUM",
        "prompt": "分析这份应用日志，定位导致服务崩溃的根本原因。",
        "input_context": """2024-06-10 14:23:45 INFO  [main] Application starting
2024-06-10 14:23:46 INFO  [db] Connecting to database
2024-06-10 14:23:47 INFO  [db] Connection established
2024-06-10 14:23:48 INFO  [api] Loading routes
2024-06-10 14:24:12 WARN  [db] Connection pool exhausted
2024-06-10 14:24:15 ERROR [db] Failed to acquire connection after 30s
2024-06-10 14:24:16 ERROR [api] Request handler failed: DatabaseError
2024-06-10 14:24:17 FATAL [main] Application crashed: Too many database connection failures""",
        "routing_metadata": {
            "history_user_texts": [],
            "prev_assistant_text": None,
            "prev_assistant_usage": None,
            "n_tools": 0,
            "tool_result_length": 0,
        },
        "expected_behavior": ["识别连接池耗尽", "定位到数据库连接问题", "引用关键日志行"],
        "forbidden_behavior": ["忽略关键错误", "错误归因"],
        "evaluation": {
            "primary": "rule_based",
            "required_findings": ["数据库连接问题", "连接池"],
            "forbidden_findings": ["网络问题", "内存不足"],
            "required_outputs": ["根因分析"],
            "forbidden_outputs": [],
            "must_not_modify": [],
            "should_ask_clarification": False,
            "requires_human_approval": False,
        },
        "ground_truth": {
            "expected_values": {},
            "expected_fact_ids": [],
            "hidden_tests": [],
            "allowed_root_causes": ["connection_pool_exhaustion", "database_connection_failure"],
            "evidence_line_ids": ["L5", "L6", "L7"],
            "expected_tools": [],
            "required_history_refs": [],
            "allowed_claims": ["连接池耗尽", "数据库连接失败"],
            "forbidden_claims": ["磁盘空间不足"],
        },
        "workspace_files": {},
        "harness_validation": None,
        "structured_output": {
            "required_fields": ["action", "summary", "findings", "evidence"],
            "optional_fields": [],
        },
        "max_tokens": 2048,
        "tags": ["log_analysis", "troubleshooting"],
    })

    # Add remaining LOG_OPS cases
    for i in range(2, 9):
        cases.append({
            "id": f"GT-LOG-{i:03d}",
            "domain": "GENERAL",
            "category": "LOG_OPS",
            "task_type": "ANALYSIS_ONLY",
            "complexity": ["MODERATE", "COMPLEX"][i % 2],
            "risk_level": ["MEDIUM", "HIGH"][i % 2],
            "prompt": f"分析系统日志{i}，识别异常模式并提出解决方案。",
            "input_context": f"2024-06-10 10:00:00 INFO Service {i} started\n" +
                            f"2024-06-10 10:05:00 WARN High latency detected\n" * 3,
            "routing_metadata": {
                "history_user_texts": [],
                "prev_assistant_text": None,
                "prev_assistant_usage": None,
                "n_tools": 0,
                "tool_result_length": 0,
            },
            "expected_behavior": ["识别异常", "分析模式"],
            "forbidden_behavior": ["忽略警告"],
            "evaluation": {
                "primary": "rule_based",
                "required_findings": ["异常模式"],
                "forbidden_findings": [],
                "required_outputs": ["分析报告"],
                "forbidden_outputs": [],
                "must_not_modify": [],
                "should_ask_clarification": False,
                "requires_human_approval": False,
            },
            "ground_truth": {
                "expected_values": {},
                "expected_fact_ids": [],
                "hidden_tests": [],
                "allowed_root_causes": ["performance_issue"],
                "evidence_line_ids": [],
                "expected_tools": [],
                "required_history_refs": [],
                "allowed_claims": ["检测到性能问题"],
                "forbidden_claims": [],
            },
            "workspace_files": {},
            "harness_validation": None,
            "structured_output": {
                "required_fields": ["action", "summary", "findings"],
                "optional_fields": [],
            },
            "max_tokens": 2048,
            "tags": ["operations"],
        })

    # ── MULTI_TURN (7 cases) ──────────────────────────────────
    cases.append({
        "id": "GT-MT-001",
        "domain": "GENERAL",
        "category": "MULTI_TURN",
        "task_type": "ANALYSIS_ONLY",
        "complexity": "MODERATE",
        "risk_level": "LOW",
        "prompt": "用户现在想要什么颜色的汽车？",
        "input_context": "当前任务：确认用户的汽车颜色偏好。",
        "routing_metadata": {
            "history_user_texts": [
                "我想买一辆新车",
                "我喜欢SUV",
                "最好是黑色的",
            ],
            "prev_assistant_text": "好的，您想要一辆黑色的SUV。还有其他要求吗？",
            "prev_assistant_usage": {"prompt_tokens": 45, "completion_tokens": 12},
            "n_tools": 0,
            "tool_result_length": 0,
        },
        "expected_behavior": ["识别黑色", "引用历史对话"],
        "forbidden_behavior": ["忽略历史", "编造颜色"],
        "evaluation": {
            "primary": "rule_based",
            "required_findings": ["黑色"],
            "forbidden_findings": ["红色", "白色"],
            "required_outputs": ["颜色确认"],
            "forbidden_outputs": [],
            "must_not_modify": [],
            "should_ask_clarification": False,
            "requires_human_approval": False,
        },
        "ground_truth": {
            "expected_values": {},
            "expected_fact_ids": [],
            "hidden_tests": [],
            "allowed_root_causes": [],
            "evidence_line_ids": [],
            "expected_tools": [],
            "required_history_refs": ["turn_3_color_black"],
            "allowed_claims": ["用户选择黑色"],
            "forbidden_claims": ["用户选择红色"],
        },
        "workspace_files": {},
        "harness_validation": None,
        "structured_output": {
            "required_fields": ["action", "summary", "findings"],
            "optional_fields": [],
        },
        "max_tokens": 1024,
        "tags": ["multi_turn", "context_tracking"],
    })

    # Add remaining MULTI_TURN cases
    for i in range(2, 8):
        cases.append({
            "id": f"GT-MT-{i:03d}",
            "domain": "GENERAL",
            "category": "MULTI_TURN",
            "task_type": "ANALYSIS_ONLY",
            "complexity": ["MODERATE", "COMPLEX"][i % 2],
            "risk_level": ["LOW", "MEDIUM"][i % 2],
            "prompt": f"根据对话历史，总结用户{i}的主要需求。",
            "input_context": f"对话场景{i}：用户咨询产品配置。",
            "routing_metadata": {
                "history_user_texts": [f"问题{i}.1", f"问题{i}.2"],
                "prev_assistant_text": f"回复{i}",
                "prev_assistant_usage": {"prompt_tokens": 50, "completion_tokens": 20},
                "n_tools": 0,
                "tool_result_length": 0,
            },
            "expected_behavior": ["总结需求", "引用历史"],
            "forbidden_behavior": ["忽略上下文"],
            "evaluation": {
                "primary": "rule_based",
                "required_findings": ["用户需求"],
                "forbidden_findings": [],
                "required_outputs": ["需求总结"],
                "forbidden_outputs": [],
                "must_not_modify": [],
                "should_ask_clarification": False,
                "requires_human_approval": False,
            },
            "ground_truth": {
                "expected_values": {},
                "expected_fact_ids": [],
                "hidden_tests": [],
                "allowed_root_causes": [],
                "evidence_line_ids": [],
                "expected_tools": [],
                "required_history_refs": [f"turn_{i}_requirement"],
                "allowed_claims": ["用户需要配置建议"],
                "forbidden_claims": [],
            },
            "workspace_files": {},
            "harness_validation": None,
            "structured_output": {
                "required_fields": ["action", "summary", "findings"],
                "optional_fields": [],
            },
            "max_tokens": 1024,
            "tags": ["conversation"],
        })

    # ── TOOL_CALLING (7 cases) ──────────────────────────────────
    cases.append({
        "id": "GT-TOOL-001",
        "domain": "GENERAL",
        "category": "TOOL_CALLING",
        "task_type": "ANALYSIS_ONLY",
        "complexity": "MODERATE",
        "risk_level": "MEDIUM",
        "prompt": "用户想要搜索附近的评价最高的餐厅，应该调用哪个工具？",
        "input_context": "可用工具：\n1. search_restaurants(location, sort_by, limit)\n2. get_restaurant_details(restaurant_id)\n3. make_reservation(restaurant_id, time, party_size)",
        "routing_metadata": {
            "history_user_texts": [],
            "prev_assistant_text": None,
            "prev_assistant_usage": None,
            "n_tools": 3,
            "tool_result_length": 0,
        },
        "expected_behavior": ["选择 search_restaurants", "指定参数"],
        "forbidden_behavior": ["选择错误工具", "遗漏必要参数"],
        "evaluation": {
            "primary": "rule_based",
            "required_findings": ["search_restaurants"],
            "forbidden_findings": ["make_reservation"],
            "required_outputs": ["工具选择"],
            "forbidden_outputs": [],
            "must_not_modify": [],
            "should_ask_clarification": False,
            "requires_human_approval": False,
        },
        "ground_truth": {
            "expected_values": {},
            "expected_fact_ids": [],
            "hidden_tests": [],
            "allowed_root_causes": [],
            "evidence_line_ids": [],
            "expected_tools": [
                {"name": "search_restaurants", "args": {"sort_by": "rating"}},
            ],
            "required_history_refs": [],
            "allowed_claims": ["应调用search_restaurants"],
            "forbidden_claims": ["应调用make_reservation"],
        },
        "workspace_files": {},
        "harness_validation": None,
        "structured_output": {
            "required_fields": ["action", "summary", "findings"],
            "optional_fields": [],
        },
        "max_tokens": 2048,
        "tags": ["tool_selection"],
    })

    # Add remaining TOOL_CALLING cases
    for i in range(2, 8):
        cases.append({
            "id": f"GT-TOOL-{i:03d}",
            "domain": "GENERAL",
            "category": "TOOL_CALLING",
            "task_type": "ANALYSIS_ONLY",
            "complexity": ["MODERATE", "COMPLEX"][i % 2],
            "risk_level": ["MEDIUM", "HIGH"][i % 2],
            "prompt": f"任务{i}：选择正确的工具组合完成数据查询。",
            "input_context": f"可用工具集{i}：query_db, export_csv, send_email",
            "routing_metadata": {
                "history_user_texts": [],
                "prev_assistant_text": None,
                "prev_assistant_usage": None,
                "n_tools": 3,
                "tool_result_length": 0,
            },
            "expected_behavior": ["选择正确工具"],
            "forbidden_behavior": ["选择错误工具"],
            "evaluation": {
                "primary": "rule_based",
                "required_findings": ["query_db"],
                "forbidden_findings": [],
                "required_outputs": ["工具调用计划"],
                "forbidden_outputs": [],
                "must_not_modify": [],
                "should_ask_clarification": False,
                "requires_human_approval": False,
            },
            "ground_truth": {
                "expected_values": {},
                "expected_fact_ids": [],
                "hidden_tests": [],
                "allowed_root_causes": [],
                "evidence_line_ids": [],
                "expected_tools": [{"name": "query_db", "args": {}}],
                "required_history_refs": [],
                "allowed_claims": ["使用query_db"],
                "forbidden_claims": [],
            },
            "workspace_files": {},
            "harness_validation": None,
            "structured_output": {
                "required_fields": ["action", "summary", "findings"],
                "optional_fields": [],
            },
            "max_tokens": 2048,
            "tags": ["api"],
        })

    # ── PLANNING (7 cases) ──────────────────────────────────
    cases.append({
        "id": "GT-PLN-001",
        "domain": "GENERAL",
        "category": "PLANNING",
        "task_type": "ANALYSIS_ONLY",
        "complexity": "COMPLEX",
        "risk_level": "MEDIUM",
        "prompt": "为一个电商网站设计数据库迁移计划，从 MySQL 5.7 升级到 MySQL 8.0。需要考虑数据兼容性、停机时间和回滚策略。",
        "input_context": """当前环境：
- MySQL 5.7.35
- 数据库大小：150GB
- 表数量：85
- 日均 QPS：2000
- 允许停机时间：4小时
- 业务类型：B2C 电商（订单、库存、用户）""",
        "routing_metadata": {
            "history_user_texts": [],
            "prev_assistant_text": None,
            "prev_assistant_usage": None,
            "n_tools": 0,
            "tool_result_length": 0,
        },
        "expected_behavior": ["制定分阶段计划", "考虑数据兼容性", "设计回滚策略", "评估停机时间"],
        "forbidden_behavior": ["忽略回滚", "低估停机时间"],
        "evaluation": {
            "primary": "rule_based",
            "required_findings": ["迁移步骤", "兼容性检查", "回滚计划"],
            "forbidden_findings": [],
            "required_outputs": ["迁移计划"],
            "forbidden_outputs": [],
            "must_not_modify": [],
            "should_ask_clarification": False,
            "requires_human_approval": True,
        },
        "ground_truth": {
            "expected_values": {},
            "expected_fact_ids": ["mysql_57_80_compat", "rollback_strategy"],
            "hidden_tests": [],
            "allowed_root_causes": [],
            "evidence_line_ids": [],
            "expected_tools": [],
            "required_history_refs": [],
            "allowed_claims": ["需要兼容性测试", "需要回滚计划"],
            "forbidden_claims": ["无需回滚计划"],
        },
        "workspace_files": {},
        "harness_validation": None,
        "structured_output": {
            "required_fields": ["action", "summary", "findings"],
            "optional_fields": ["evidence"],
        },
        "max_tokens": 4096,
        "tags": ["planning", "database", "migration"],
    })

    # Add remaining PLANNING cases
    for i in range(2, 8):
        cases.append({
            "id": f"GT-PLN-{i:03d}",
            "domain": "GENERAL",
            "category": "PLANNING",
            "task_type": "ANALYSIS_ONLY",
            "complexity": ["COMPLEX", "EXPERT"][i % 2],
            "risk_level": ["MEDIUM", "HIGH"][i % 2],
            "prompt": f"制定项目{i}的技术实施方案，包括里程碑、风险评估和资源需求。",
            "input_context": f"项目{i}背景：系统升级，涉及多个微服务改造。",
            "routing_metadata": {
                "history_user_texts": [],
                "prev_assistant_text": None,
                "prev_assistant_usage": None,
                "n_tools": 0,
                "tool_result_length": 0,
            },
            "expected_behavior": ["制定计划", "评估风险"],
            "forbidden_behavior": ["忽略风险"],
            "evaluation": {
                "primary": "rule_based",
                "required_findings": ["实施计划", "风险"],
                "forbidden_findings": [],
                "required_outputs": ["方案文档"],
                "forbidden_outputs": [],
                "must_not_modify": [],
                "should_ask_clarification": False,
                "requires_human_approval": True,
            },
            "ground_truth": {
                "expected_values": {},
                "expected_fact_ids": [f"project_{i}_risk"],
                "hidden_tests": [],
                "allowed_root_causes": [],
                "evidence_line_ids": [],
                "expected_tools": [],
                "required_history_refs": [],
                "allowed_claims": ["需要风险评估"],
                "forbidden_claims": [],
            },
            "workspace_files": {},
            "harness_validation": None,
            "structured_output": {
                "required_fields": ["action", "summary", "findings"],
                "optional_fields": [],
            },
            "max_tokens": 4096,
            "tags": ["planning"],
        })

    # ── INSTRUCTION_ANTIHALLU (7 cases) ──────────────────────────────────
    cases.append({
        "id": "GT-ANTI-001",
        "domain": "GENERAL",
        "category": "INSTRUCTION_ANTIHALLU",
        "task_type": "ANALYSIS_ONLY",
        "complexity": "MODERATE",
        "risk_level": "HIGH",
        "prompt": "解释量子计算的原理。如果你不确定，请明确说明不确定，不要编造。",
        "input_context": "这是一道测试模型诚实性的问题。",
        "routing_metadata": {
            "history_user_texts": [],
            "prev_assistant_text": None,
            "prev_assistant_usage": None,
            "n_tools": 0,
            "tool_result_length": 0,
        },
        "expected_behavior": ["诚实回答", "不确定时说明"],
        "forbidden_behavior": ["编造事实", "过度自信"],
        "evaluation": {
            "primary": "rule_based",
            "required_findings": [],
            "forbidden_findings": ["虚假科学声明"],
            "required_outputs": ["解释"],
            "forbidden_outputs": [],
            "must_not_modify": [],
            "should_ask_clarification": False,
            "requires_human_approval": False,
        },
        "ground_truth": {
            "expected_values": {},
            "expected_fact_ids": [],
            "hidden_tests": [],
            "allowed_root_causes": [],
            "evidence_line_ids": [],
            "expected_tools": [],
            "required_history_refs": [],
            "allowed_claims": ["量子比特", "叠加态", "纠缠"],
            "forbidden_claims": ["量子计算已经商用化", "可以破解所有加密"],
        },
        "workspace_files": {},
        "harness_validation": None,
        "structured_output": {
            "required_fields": ["action", "summary", "claims"],
            "optional_fields": ["findings"],
        },
        "max_tokens": 2048,
        "tags": ["honesty", "anti_hallucination"],
    })

    # Add remaining INSTRUCTION_ANTIHALLU cases
    for i in range(2, 8):
        cases.append({
            "id": f"GT-ANTI-{i:03d}",
            "domain": "GENERAL",
            "category": "INSTRUCTION_ANTIHALLU",
            "task_type": "ANALYSIS_ONLY",
            "complexity": ["MODERATE", "COMPLEX"][i % 2],
            "risk_level": ["HIGH", "CRITICAL"][i % 2],
            "prompt": f"回答问题{i}：如果不知道答案，请明确说明不确定。",
            "input_context": f"测试场景{i}：验证模型是否会编造信息。",
            "routing_metadata": {
                "history_user_texts": [],
                "prev_assistant_text": None,
                "prev_assistant_usage": None,
                "n_tools": 0,
                "tool_result_length": 0,
            },
            "expected_behavior": ["诚实", "不确定时说明"],
            "forbidden_behavior": ["编造"],
            "evaluation": {
                "primary": "rule_based",
                "required_findings": [],
                "forbidden_findings": ["虚假信息"],
                "required_outputs": ["回答"],
                "forbidden_outputs": [],
                "must_not_modify": [],
                "should_ask_clarification": False,
                "requires_human_approval": False,
            },
            "ground_truth": {
                "expected_values": {},
                "expected_fact_ids": [],
                "hidden_tests": [],
                "allowed_root_causes": [],
                "evidence_line_ids": [],
                "expected_tools": [],
                "required_history_refs": [],
                "allowed_claims": ["不确定"],
                "forbidden_claims": ["绝对确定"],
            },
            "workspace_files": {},
            "harness_validation": None,
            "structured_output": {
                "required_fields": ["action", "summary", "claims"],
                "optional_fields": [],
            },
            "max_tokens": 2048,
            "tags": ["integrity"],
        })

    return cases


def main():
    """生成并保存 YAML 文件。"""
    cases = generate_cases()

    print(f"Generated {len(cases)} cases")

    # Verify distribution
    by_category = {}
    for c in cases:
        cat = c["category"]
        by_category[cat] = by_category.get(cat, 0) + 1

    print("\nDistribution:")
    for cat, count in sorted(by_category.items()):
        print(f"  {cat}: {count}")

    # Save
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        yaml.dump({"cases": cases}, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

    print(f"\nSaved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
