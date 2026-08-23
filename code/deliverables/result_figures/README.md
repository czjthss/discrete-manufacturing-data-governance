# 实测成果图说明

图中数值直接读取 `../指标3.1-3.9测试结果.json`。`figure_manifest.json` 记录原有成果图的来源与文件摘要，`indicator_panels_manifest.json` 记录三张指标成果图的报告 SHA-256、文件字节数和文件 SHA-256。

| 文件 | 用途 | 关键内容 |
|---|---|---|
| `indicator_panels_1_3.png` | 指标①-③ | MetroPT-3、FordA TRAIN+TEST 序列存储和误差有界压缩，SECOM、HoloClean Hospital 关系存储 |
| `indicator_panels_4_6.png` | 指标④-⑥ | MetroPT-3 全量总体对齐、四套数据完整解析、两套时序数据 7 次软件吞吐测量 |
| `indicator_panels_7_9.png` | 指标⑦-⑨ | MetroPT-3 全量总体融合、四套数据规范化、四套数据的可评价质量维度 |
| `candidate_1_overview.png` | 项目汇报、成果材料首图 | 9 项全部通过，压缩、解析、对齐、吞吐和质量核心数值 |
| `candidate_2_compression.png` | 技术成果、压缩算法说明 | MetroPT-3 官方完整数据总体、最差块、最差通道及全部 15 个通道结果 |
| `candidate_3_quality.png` | 验收说明、质量评测 | 3.3/3.4 固定标注样例结果与描述性 Wilson 区间，3.6/3.9 多维质量得分 |
| `candidate_4_throughput.png` | 性能说明、技术附件 | 预热后 7 次软件接收吞吐原始结果，对数坐标展示 1.1 kHz 目标 |
| `candidate_contact_sheet.png` | 选图预览 | 4 张候选图的缩略总览 |
| `assessment_result_1_evidence_board.png` | 项目汇报、考核材料 | 逐项展示 9 条考核指标、状态、实测证据和对应模块 |
| `assessment_result_2_capability_map.png` | 答辩、技术路线说明 | 展示治理能力闭环及 9 条考核指标映射 |
| `benchmark_result_1_forda_pipeline.png` | 公开数据案例、成果汇报 | UCR FordA 原始序列、压缩重构、解析、关系表、对齐融合样例 |
| `benchmark_result_2_forda_quality.png` | 公开数据案例、质量治理说明 | FordA 真实波形与吞吐测量，以及 MetroPT-3、SECOM、HoloClean Hospital 八维质量结果 |

## 口径

- 3.3 覆盖四套数据的完整固定发布范围；3.4 覆盖 MetroPT-3 官方完整 1,516,948 行及官方说明中的 4 个维护/故障时间区间。准确率和 Wilson 95% 区间只描述这些固定范围，不推断其他业务数据。
- 3.5 表示同一 Python 进程内的环形缓冲区批量写入速率，不等同于采集卡至存储系统的端到端吞吐。
- 3.1 展示文件级 Gzip 或 SQLite 备份 Gzip 的无损存储压缩；3.2 展示误差有界专用时序编码，两者的原始字节定义、编码目标和算法均不同，不能直接比较压缩比。
- 3.2 覆盖 MetroPT-3 官方完整 1,516,948 行、全部 15 个传感器通道，以及 UCR FordA TRAIN+TEST 全部 4,921 条序列、2,460,500 个点。图中箱线图展示所有数据块、通道或序列单元，没有只选取高表现子集。
- 3.4 和 3.7 只显示 MetroPT-3 全量总体结果，不拆分时间窗。关系侧使用该数据集官方说明中的维护/故障区间。
- 质量热力图中的 `N/A` 表示该公开数据不提供对应评价真值，不作为零分或通过值参与汇总。

## 数据属性

- MetroPT-3 是地铁空气压缩机预测性维护数据，UCI SECOM 是半导体制造过程数据，二者属于真实工业领域数据。
- UCR FordA 来源于汽车子系统电机测量，发布版本已经过抽样、归一化和分类任务加工，属于工业来源的领域基准。
- HoloClean Hospital 是医疗关系数据清洗真值基准，不属于工业数据；用于补充关系数据解析、存储和质量真值评价。
- 本组图及对应正式实验只使用 MetroPT-3、UCR FordA TRAIN+TEST、UCI SECOM 和 HoloClean Hospital 四套数据。

## 重新生成

需要 Python 3.11 或更高版本、Matplotlib 和 Pillow。从 `code` 目录执行：

```bash
MPLCONFIGDIR=/tmp/matplotlib-cache python3 tools/build_result_figures.py
python3 tools/build_assessment_figures.py
python3 tools/build_public_benchmark_figures.py
python3 tools/build_indicator_subplots.py
```
