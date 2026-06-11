# OpenSquilla ML 复杂度路由集成 — 实施计划

> 本文档保存最终实施计划和验收清单。详细设计见 `system-design-ml-complexity-extension.md`。

## 概述

将 OpenSquilla 的 ML 路由分类器（LightGBM + ONNX MLP 双头集成）作为 AirRouter 的**可选增强**集成，提升复杂度判断准确性。

## 实施阶段

### Phase 1: 基础设施
- 1a: 抽取复杂度规则逻辑到 `router/rule_logic.py`
- 1b: 定义数据类型（`complexity/types.py`）
- 1c: 配置（`ComplexityConfig` + `data/complexity.yaml`）

### Phase 2: ML 后端 + Artifact 安全校验
- 2a: Artifact SHA-256 校验（`artifact_verifier.py`）
- 2b: OpenSquilla 运行时封装（`ml_backend.py`）
- 2c: pyproject.toml 添加 ml 可选依赖
- 2d: ML 后端测试

### Phase 3: 统一 ComplexityAnalyzer + Router 集成
- 3a: ComplexityAnalyzer（4 种 mode + 7 字段资源重算）
- 3b: Router 集成（单一 analyzer 入口）
- 3c: ComplexityDiagnostics Pydantic 模型
- 3d: Analyzer 测试

### Phase 4: CLI 和校准报告
- 4a: CLI analyze 命令扩展（`--show-complexity`）
- 4b: 校准报告脚本

### Phase 5: 文档和收口
- 5a: 许可证文件
- 5b: 集成文档完善
- 5c: 全量测试

## 验收清单

- [ ] `mode: rules` 下所有已有测试零行为变化
- [ ] `mode: rules` 时不创建 Backend 实例
- [ ] `mode: hybrid` 使用 raw class，confidence < threshold 不升级
- [ ] `mode: opensquilla` 下降级时 7 个资源字段完整替换
- [ ] ML 依赖未安装时 `mode: rules` 正常工作
- [ ] Artifact SHA-256 校验拦截篡改文件
- [ ] `predict()` 只返回真实 MLPrediction 或抛异常
- [ ] `make lint && pytest tests/ -q` 全部通过
