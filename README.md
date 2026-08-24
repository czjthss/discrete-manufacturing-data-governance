# Discrete Manufacturing Data Governance

面向离散制造垂域模型的自动化数据治理系统。项目提供可运行的 Python 服务、网页工作台、逐指标测试程序和公开基准证据。

## 核心能力

- **存储压缩**：支持序列与关系数据存储、无损回读和工业时序误差有界压缩。
- **结构解析**：解析 CSV、TSV、JSON、JSONL、XML 和 INI，并校验结构与字段。
- **语义对齐**：统一实体、字段和事件时间，按设备及时间窗关联序列与关系记录。
- **高频采集**：使用批量环形缓冲区接收时序记录，测量最低吞吐与数据丢失。
- **质量稳控**：评价完整性、一致性、时效性和有效性，并执行确定性清洗与异常隔离。
- **数据融合**：保留原始序列记录，同时附加匹配的设备、工单或维护信息。
- **工业数据规范化**：通过可扩展适配器把异构输入转换为统一中间表示。
- **综合测评**：汇总质量维度、真值核验、参照完整性和数据血缘，形成可审计报告。

## 公开验证

正式实验使用 MetroPT-3、UCR FordA、UCI SECOM 和 HoloClean Hospital。时序实验覆盖 MetroPT-3 官方完整 1,516,948 行和 FordA TRAIN+TEST 全部 4,921 条序列；关系实验覆盖 SECOM 全部 1,567 条记录和 Hospital 全部 1,000 行及 19,000 个清洁真值单元格。

- [正式测试结果](code/deliverables/指标3.1-3.9测试结果.json)
- [算法测试大纲](code/docs/课题三指标3.1-3.9算法测试大纲与运行说明.md)
- [成果图说明](code/deliverables/result_figures/README.md)
- [数据来源与固定版本](code/governance/benchmark_data/public/README.md)

## 已有成果

`reger_bos_code_paths/` 保存已有时序压缩实现，并通过统一适配器接入系统：

- REGER：支持 Int64 与 Float64 编解码。
- BOS：支持分块差分、ZigZag 和变长整数编码。
- TS_2DIFF+BOS：在候选编码间按载荷选择，支持整数和浮点输入。

这些实现设有独立往返一致性测试。指标 3.2 的正式验收结果由完整公开数据上的统一时序压缩流程产生，不混用不同数据范围的结果。

## 运行

```bash
cd code
python3 run.py
```

浏览器访问 `http://127.0.0.1:8000`。项目建议使用 Python 3.11 或更高版本，核心服务仅依赖 Python 标准库。

```bash
PYTHONPATH=code python3 -m unittest discover -s code/tests -p 'test_*.py'
cd code
python3 run_indicator_tests.py all
```

## 项目结构

```text
code/
  app.py                         Web 服务与 API
  governance/                    指标 3.1-3.9 算法
  integrations/                  压缩与论文方法适配器
  static/                        网页工作台
  tests/                         单元、对抗和逐指标测试
  docs/                          测试大纲与运行说明
  deliverables/                  正式报告、成果图和交付包
reger_bos_code_paths/            已有压缩实现
```

实现细节、接口和数据边界见 [code/README.md](code/README.md)。
