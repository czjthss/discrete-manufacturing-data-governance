# 技术依据与集成状态

系统核心路径使用 Python 标准库。外部论文与开源项目用于确定算法思路和接口边界；只有许可证、版本和运行入口均确认的代码才能登记为可运行实现。

## 技术依据

- **时序压缩**：Gorilla（PVLDB 2015）提供时序预测编码思路；SZ3 提供误差界、预测器和编码器分层方法。当前实现按数据类型执行误差有界量化差分或无损编码，并逐块解码核验。
- **压缩态查询**：CompressIoTDB（PVLDB 2025）提供块级裁剪、压缩态范围过滤和延迟解压思路。
- **时序质量**：TsQuality（PVLDB 2023）提供基于事件时间窗口的完整性、一致性、时效性和有效性评价方法。
- **语义匹配**：Matchmaker（ICML 2025）与 Ditto（PVLDB 2020）提供候选生成、实体匹配和领域知识约束方法。
- **嵌入式融合**：DuckDB（SIGMOD 2019）提供进程内列式分析思路；当前关系存储使用 SQLite，并通过稳定接口隔离实现。
- **质量规则**：Great Expectations 提供可重复执行、可留证据的规则组织方式。

## 论文与项目

| 名称 | 论文或项目 | 当前状态 |
|---|---|---|
| Gorilla | https://www.vldb.org/pvldb/vol8/p1816-teller.pdf | 方法参考 |
| SZ3 | https://github.com/szcompressor/SZ3 | 方法参考 |
| CompressIoTDB | https://www.vldb.org/pvldb/vol18/p3406-tang.pdf | 已实现方法适配器；官方仓库未嵌入 |
| Apache TsFile | https://github.com/apache/tsfile | 保留适配接口；未固定接入 commit |
| TsQuality | https://www.vldb.org/pvldb/vol16/p3982-song.pdf | 已实现窗口质量适配器 |
| Matchmaker | https://openreview.net/forum?id=clLERWKNja | 已实现候选与置信度适配器 |
| Ditto | https://github.com/megagonlabs/ditto | 方法参考 |
| DuckDB | https://duckdb.org/library/duckdb/ | 方法参考 |
| Great Expectations | https://github.com/great-expectations/great_expectations | 规则组织参考 |

## 正式公开基准

- **MetroPT-3**：UCI DOI `10.24432/C5VW3R`；真实地铁空气生产单元多变量时序，带维护区间。
- **UCR FordA**：DOI `10.5281/zenodo.11191164`；汽车系统等长时序分类基准。
- **UCI SECOM**：UCI DOI `10.24432/C54305`；真实半导体制造过程数据，包含自然缺失值。
- **HoloClean Hospital**：Rekatsinas et al., PVLDB 2017；提供关系数据全单元格清洁真值。

固定文件、数据范围和 SHA-256 见 `governance/benchmark_data/public/benchmark_manifest.json`。NASA IMS、JSONTestSuite 和 W3C XML 套件只保留为补充回归资产，不计入当前四数据集正式结果。

## 集成要求

外部实现接入前必须记录论文链接、仓库 URL、许可证、固定 commit、引入文件、本地修改、模型权重和训练数据许可，并在同一公开基准口径下复测相关指标。许可证兼容性未确认的代码不得复制到系统主体。
