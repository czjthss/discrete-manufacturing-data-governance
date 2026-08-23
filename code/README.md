# 面向离散制造垂域模型的自动化数据治理系统

这是课题三面向项目里程碑2的可运行实现。系统覆盖序列与关系数据的存储压缩、解析、对齐、高频采集、质量稳控、数据融合，以及工业数据规范化和综合测评框架。

## 启动

```bash
cd code
python3 run.py
```

浏览器访问 `http://127.0.0.1:8000`。

首版不依赖第三方 Python 包，建议使用 Python 3.11 或更高版本。服务启动后可在网页中：

- 一键运行 3.1–3.9 全部公开基准测试并生成 `data/reports/latest-self-test.json`；
- 分别运行每项指标；
- 导入或粘贴 CSV、TSV、JSON、JSONL、XML、INI 数据；
- 查看七维质量画像与规范化预览；
- 运行序列数据与工单关系的融合演示。
- 在“技术集成”视图查看每项指标的当前方法、待接入论文/代码、许可证和 commit 状态。

后端还提供：

- `GET /api/indicators`：指标、当前方法和计划接入项；
- `GET /api/integrations`：算法注册表、运行状态及 3.1–3.9 映射；
- `GET /api/references`：论文、仓库、许可证与 commit 元数据。

## 逐指标测试

在本目录可单独测试 3.1–3.9，也可一次运行全部指标并生成包含环境、源码版本和基准结果的 JSON 报告：

```bash
python3 run_indicator_tests.py 3.1
python3 run_indicator_tests.py all
```

各指标的算法文件、公开数据、测试文件、通过判据和逐项命令见 `algorithm_manifest.json`。完整测试大纲与运行说明见 `docs/课题三指标3.1-3.9算法测试大纲与运行说明.md` 或同名 Word 文档。

## 公开基准

当前实验只使用固定版本的 MetroPT-3、UCR FordA、UCI SECOM 和 HoloClean Hospital。所有文件在加载前按 `governance/benchmark_data/public/benchmark_manifest.json` 校验大小与 SHA-256；手写样例只验证异常输入、安全边界和错误处理，不参与指标得分。

| 基准 | 用途 | 固定测试范围 |
|---|---|---|
| UCI MetroPT-3 | 工业时序存储、压缩、解析、对齐、吞吐、融合与质量 | 官方完整 1,516,948 行、全部 15 个传感器通道；对齐与融合使用官方说明中的四个维护/故障时间区间 |
| UCR FordA | 工业来源时序存储、压缩、解析、吞吐与质量 | TRAIN+TEST 两个官方分割全部 4,921 条、每条 500 点，共 2,460,500 个时序点 |
| UCI SECOM | 制造关系数据存储、解析、规范化与质量 | 1,567 条半导体制造记录、590 个传感器字段及原始缺失值 |
| HoloClean Hospital | 关系数据存储、解析、规范化与真值质量 | 1,000 行脏数据和 19,000 个单元格清洁真值；作为非工业关系真值补充 |

数据来源、许可证、固定 commit、选样规则和文件指纹见 `governance/benchmark_data/public/README.md`。首次运行 3.2 前下载并校验官方完整归档：

```bash
python3 tools/fetch_full_benchmarks.py
```

如需从所有官方归档重新生成其他固定数据，可运行：

```bash
python3 tools/prepare_public_benchmarks.py --help
```

确定性生成含逐文件 SHA-256 清单的交付压缩包：

```bash
python3 tools/build_delivery_package.py
```

## 产物保留

系统以原子替换写入报告和序列文件，并通过目录级文件锁协调多进程清理。默认分别保留 256 份自测报告、256 份治理报告、128 个 3.1 自测运行目录和 256 份分析序列。报告与分析序列在写入后至少保留 600 秒；3.1 运行目录只有生成原子 `.completed` 标记并超过该保护期后才会成为清理候选。因此数量上限允许在保护期内暂时超出，写入方返回的路径不会立即被其他进程删除。

可通过以下环境变量调整各类别数量，值必须为正整数：

- `DGOV_RETENTION_RUN_REPORTS`
- `DGOV_RETENTION_GOVERNANCE_REPORTS`
- `DGOV_RETENTION_STORAGE_RUNS`
- `DGOV_RETENTION_ANALYSIS_SEQUENCES`
- `DGOV_RETENTION_GRACE_SECONDS`（默认 `600`，可设为非负秒数）

## 指标映射

| 指标 | 文件 | 里程碑2实现 |
|---|---|---|
| 3.1 | `governance/indicator_3_1.py` | 序列与关系数据存储、压缩、回读 |
| 3.2 | `governance/indicator_3_2.py` | 全量流式时序压缩；总体、最差块和最差通道均达到 9:1 |
| 3.3 | `governance/indicator_3_3.py` | 格式识别与结构解析，目标 ≥95% |
| 3.4 | `governance/indicator_3_4.py` | 字段语义统一与时间窗对齐，目标 ≥90% |
| 3.5 | `governance/indicator_3_5.py` | 批量环形缓冲采集，目标 1.1kHz |
| 3.6 | `governance/indicator_3_6.py` | 完整性、一致性、时效性、有效性 ≥95% |
| 3.7 | `governance/indicator_3_7.py` | 序列数据与关系数据按需融合 |
| 3.8 | `governance/indicator_3_8.py` | 可扩展异构格式规范化测试框架 |
| 3.9 | `governance/indicator_3_9.py` | 八维工业数据质量综合测评 |

## 验收说明

本系统输出可复现的公开基准证据，并记录运行环境、测量过程和结果，用于项目复验与验收材料整理。

压缩模块流式读取 MetroPT-3 官方完整 1,516,948 行和全部 15 个传感器通道，并处理 UCR FordA TRAIN+TEST 全部 4,921 条序列。MetroPT-3 原始载荷按七个模拟量 Float64 与八个数字量 UInt8 计；时间戳不计入传感器压缩口径。模拟量采用固定误差界量化差分编码，数字量无损编码，每个数据块或序列均完整解码核验；9:1 判据同时约束两套时序数据的总体与最差单元结果。1.1 kHz 项是在同一软件边界完整回放 MetroPT-3 与 FordA 后的内存接收吞吐，不代表采集卡、传感器和网络链路的现场整机结论。SECOM 的时效性按归档数据观察窗口计算，不解释为相对当前日期的新鲜度。
