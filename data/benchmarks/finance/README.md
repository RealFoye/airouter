# Finance Office Benchmark

这是一份企业财务办公场景 benchmark 数据包，全部数据均为 synthetic fiction，不包含公司真实数据。

## 目标

测量模型在财务日常工作中的落地能力，而不是通用榜单能力：

- 表格理解、分类汇总、数值计算
- 报销制度套用和违规识别
- 合同 / PO / 发票 / 验收三单匹配
- 银行流水与账簿对账
- 预算执行差异分析
- 财务制度问答和硬约束提取

## 数据规模

- 36 cases
- 6 个类别，每类 6 条
- 5 个模型时为 180 次模型执行，不含 judge

## 公开 benchmark 借鉴

本数据包参考公开 benchmark 的任务形态，但不复制公开 case：

- SpreadsheetBench: spreadsheet/Excel 操作任务形态
- FinanceBench: 金融文档问答和证据定位形态
- FinQA / TAT-QA: 表格 + 文本的金融数值推理
- DocILE: invoices / purchase orders / line items 的文档理解任务形态

## 推荐评分策略

财务场景不要只靠 LLM Judge。建议优先规则评分：

1. JSON 是否可解析
2. 金额字段是否正确，容忍 0.01 CNY
3. required_findings 是否召回
4. forbidden_findings 是否避免
5. evidence 是否能引用输入表/制度
6. LLM Judge 只评解释质量，不覆盖金额真值

## 文件

- `finance_cases.yaml`: benchmark case 主文件
- `artifacts/policies/*.md`: synthetic 财务制度
- `artifacts/expenses/*.csv`: 报销明细
- `artifacts/ap/*.csv`: 合同 / PO / 发票 / 验收匹配
- `artifacts/bank/*.csv`: 银行流水与账簿
- `artifacts/budget/*.csv`: 预算执行表
