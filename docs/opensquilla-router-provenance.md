# OpenSquilla Router Bundle 来源与版本追溯

## Bundle 信息

| 项目 | 值 |
|------|-----|
| 来源仓库 | https://github.com/opensquilla/opensquilla |
| 仓库 Commit | `5409a22a5205846a6f9998e2d361cf286d8caa8d` |
| 模型版本 | v4.2 (phase 3 inference) |
| Bundle 路径 | `opensquilla/src/opensquilla/squilla_router/models/v4.2_phase3_inference/` |
| 许可证 | Apache License 2.0 |

## 模型组成

| 组件 | 文件 | 说明 |
|------|------|------|
| LightGBM 主模型 | `lgbm_main.bin` | 390 维特征 → R0-R3 |
| LightGBM 辅助模型 | `lgbm_aux.bin` | 可选辅助分类头 |
| ONNX MLP | `mlp/` | 1536 维 BGE 三通道嵌入 |
| BGE 嵌入模型 | `bge_onnx/` | BAAI/bge-small-zh-v1.5 (MIT) |
| 特征工程 | `features/` | TF-IDF vocab, PCA, scalers |
| 运行时源码 | `runtime_src/` | InferenceCore + 特征管线 |
| 运行时配置 | `router.runtime.yaml` | 模型加载和推理参数 |
| Artifact 清单 | `artifact_manifest.json` | 文件 SHA-256 校验清单 |

## 安全校验

AirRouter 在加载前通过 `ArtifactVerifier` 进行以下校验：

1. **Manifest 完整性** — manifest 文件自身的 SHA-256 必须与硬编码锚点匹配
2. **运行时配置完整性** — `router.runtime.yaml` 的 SHA-256 校验
3. **源码树完整性** — `runtime_src/` 下所有 `.py` 文件的树摘要 SHA-256 校验
4. **文件存在性** — manifest 声明的所有文件必须存在
5. **文件大小** — 与 manifest 声明严格相等
6. **文件哈希** — 每个文件的 SHA-256 与 manifest 一致
7. **拒绝 symlink** — 整个 bundle 中不允许符号链接
8. **拒绝意外二进制** — 不允许 `.so`/`.dylib`/`.pyd` 文件

## 部署方式

Bundle **不随 AirRouter 分发**，需通过以下方式获取：

1. 从 OpenSquilla 仓库获取模型文件
2. 设置环境变量 `AIROUTER_OPENSQUILLA_BUNDLE_DIR` 指向 bundle 目录
3. 安装 ML 可选依赖：`pip install airouter[ml]`

## 版本变更记录

| 日期 | 变更 |
|------|------|
| 2026-06-11 | 首次集成，基于 commit 5409a22 |
