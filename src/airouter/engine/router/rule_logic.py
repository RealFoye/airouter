"""复杂度推断规则逻辑。

从 analyzer.py 抽取，供 complexity/ 模块复用，避免循环依赖。
"""

from __future__ import annotations

from airouter.models.enums import ComplexityLevel

# ── 复杂度推断规则 ──────────────────────────────────────────
COMPLEXITY_KEYWORDS: dict[ComplexityLevel, list[str]] = {
    ComplexityLevel.EXPERT: [
        "系统级", "全局", "跨域", "多租户", "百万级", "千万级",
        "核心算法", "新算法", "领域专家", "百万并发",
    ],
    ComplexityLevel.COMPLEX: [
        "跨模块", "多文件", "中间件", "网关", "分布式",
        "高并发", "鉴权", "OAuth", "MFA", "权限管理",
        "安全模块", "并发", "死锁", "内存泄漏",
        "God Class", "策略模式", "Repository",
    ],
    ComplexityLevel.MODERATE: [
        "多个", "几个", "相关", "一些", "部分", "模块",
        "多个文件", "相关模块", "安全漏洞", "数据清洗",
        "Docker Compose", "数据库", "登录", "整个项目",
    ],
    # SIMPLE 是默认，不需要关键词
}


def infer_complexity(desc: str, desc_lower: str | None = None) -> ComplexityLevel:
    """基于关键词推断任务复杂度。

    按 EXPERT → COMPLEX → MODERATE 优先级匹配，未命中则返回 SIMPLE。
    """
    if desc_lower is None:
        desc_lower = desc.lower()
    for level in [ComplexityLevel.EXPERT, ComplexityLevel.COMPLEX, ComplexityLevel.MODERATE]:
        for kw in COMPLEXITY_KEYWORDS.get(level, []):
            if kw.lower() in desc_lower or kw in desc:
                return level
    return ComplexityLevel.SIMPLE
