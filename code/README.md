# 面向离散制造垂域模型的自动化数据治理系统

本目录包含系统后端、网页工作台、指标 3.1-3.9 算法、公开基准加载器和测试程序。

## 能力模块

- **存储压缩（3.1、3.2）**：序列文件、关系数据库、压缩备份和误差有界时序编码。
- **结构解析（3.3）**：格式识别、严格解析、字段检查和错误输入拒绝。
- **语义对齐（3.4）**：字段归一、实体匹配和维护时间窗对齐。
- **高频采集（3.5）**：批量环形缓冲、重复吞吐测量和零丢失检查。
- **质量稳控（3.6）**：完整性、一致性、时效性和有效性评价。
- **数据融合（3.7）**：序列数据与关系数据左融合，并保留未匹配原始记录。
- **工业数据规范化（3.8）**：将异构格式转换为统一记录结构。
- **综合测评（3.9）**：综合基础质量、唯一性、参照完整性、真值准确率和可追溯性。

每项指标分别实现在 `governance/indicator_3_1.py` 至 `governance/indicator_3_9.py`。

## 启动

```bash
python3 run.py
```

浏览器访问 `http://127.0.0.1:8000`。建议使用 Python 3.11 或更高版本。

网页支持运行全部或单项指标测试、导入异构数据、配置治理规则、查看质量变化与血缘，并下载测试报告。

## 公开基准

| 数据集 | 数据类型 | 正式测试范围 |
|---|---|---|
| MetroPT-3 | 工业多变量时序 | 官方完整 1,516,948 行、15 个传感器通道和 4 个维护区间 |
| UCR FordA | 汽车系统时序 | TRAIN+TEST 全部 4,921 条序列，每条 500 点 |
| UCI SECOM | 半导体制造关系数据 | 全部 1,567 条记录、590 个传感器字段和原始缺失值 |
| HoloClean Hospital | 关系数据质量真值 | 全部 1,000 行和 19,000 个清洁真值单元格 |

加载器按 `governance/benchmark_data/public/benchmark_manifest.json` 校验文件大小和 SHA-256。手写输入只用于异常、边界和安全回归，不计入指标得分。MetroPT-3 完整归档首次使用前运行：

```bash
python3 tools/fetch_full_benchmarks.py
```

## 测试与证据

```bash
# 单项测试
python3 run_indicator_tests.py 3.1

# 全部指标
python3 run_indicator_tests.py all

# 工程测试
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_*.py'
```

正式结果保存在 `deliverables/指标3.1-3.9测试结果.json`。算法文件、数据范围、通过判据和运行命令见：

- `algorithm_manifest.json`
- `docs/课题三指标3.1-3.9算法测试大纲与运行说明.md`
- `docs/课题三指标3.1-3.9算法测试大纲与运行说明.docx`

交付包通过 `python3 tools/build_delivery_package.py` 生成，包内 `PACKAGE_MANIFEST.json` 记录逐文件 SHA-256。

## 服务接口

- **测试**：`/api/benchmark/all`、`/api/benchmark/{id}`。
- **治理**：`/api/analyze`、`/api/rules/validate`、`/api/fusion/demo`。
- **证据**：`/api/report/latest`、`/api/reports`、`/api/reports/download/{name}`。
- **元数据**：`/api/health`、`/api/indicators`、`/api/integrations`、`/api/references`。

## 运行边界

- 3.2 的压缩比按声明的原始传感器字节类型和误差界计算，不包含 CSV 文本、时间戳、容器索引或网络协议开销。
- 3.5 测量 Python 软件边界的接收与缓冲吞吐，不代表传感器、采集卡、驱动和网络链路的现场整机性能。
- 归档数据的时效性按各数据集观察窗口评价，不解释为相对当前日期的新鲜度。

报告和存储产物采用独立运行标识、原子替换和进程安全清理。保留数量可通过 `DGOV_RETENTION_RUN_REPORTS`、`DGOV_RETENTION_GOVERNANCE_REPORTS`、`DGOV_RETENTION_STORAGE_RUNS`、`DGOV_RETENTION_ANALYSIS_SEQUENCES` 和 `DGOV_RETENTION_GRACE_SECONDS` 调整。
