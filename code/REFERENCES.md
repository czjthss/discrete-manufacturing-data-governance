# 技术依据与后续集成清单

系统默认运行路径保持零外部依赖，并支持里程碑2逐项测量。当前没有直接复制许可证或版本尚未确认的第三方仓库代码；项目自有适配器采用公开论文中的方法，并保留官方实现替换接口。引入论文附属代码时，应固定提交版本并复测全部指标。

## 当前采用的技术思路

### 时序存储与压缩（3.1、3.2）

- Gorilla, *A Fast, Scalable, In-Memory Time Series Database*, PVLDB 2015  
  论文：https://www.vldb.org/pvldb/vol8/p1816-teller.pdf  
  参考点：利用时间序列连续性做预测编码，压缩结果必须可测量和可恢复。
- SZ3: A Modular Framework for Composing Prediction-Based Error-Bounded Lossy Compressors  
  代码：https://github.com/szcompressor/SZ3  
  参考点：误差界、预测器和编码器分层。首版 `PiecewiseLinearCodec` 使用有界误差分段线性表示，并在报告中同时披露误差界和压缩比。

## 论文方法与官方实现状态

### CompressIoTDB（3.1、3.2、3.7）

- *Improving Time Series Data Compression in Apache IoTDB*, PVLDB 2025  
  论文：https://www.vldb.org/pvldb/vol18/p3406-tang.pdf  
  代码：https://github.com/yuxin370/CompressIoTDB  
  已适配方法：块级最值裁剪、压缩态范围过滤和 late decompression。
  官方仓库代码的许可证及 commit SHA 待接入时确认。

### Apache TsFile / IoTDB（3.1、3.2、3.5）

- 官方项目：https://tsfile.apache.org/  
  代码：https://github.com/apache/tsfile  
  计划接入：工业时序列式文件、设备/时间索引、GORILLA 编码和 LZ4 压缩。
  仓库许可证为 Apache-2.0，具体接入 commit 尚未固定。

### TsQuality（3.6、3.9）

- *TsQuality: Measuring Time Series Data Quality in Apache IoTDB*, VLDB 2023  
  论文：https://www.vldb.org/pvldb/vol16/p3982-song.pdf  
  项目：https://thssdb.github.io/TsQuality/  
  已适配方法：基于事件时间窗口的 completeness、consistency、timeliness、
  validity 四维计算。当前实现没有复制论文附属代码。

### Matchmaker（3.4、3.8）

- *Bootstrapping Self-Improvement of Language Model Programs for Zero-Shot Schema Matching*,
  ICML 2025  
  论文：https://openreview.net/forum?id=clLERWKNja  
  已适配方法：候选生成、别名精炼、置信度评分和拒绝阈值。尚未确认可接入的
  官方代码仓库、许可证和 commit。

### 语义对齐（3.4）

- Ditto, *Deep Entity Matching with Pre-Trained Language Models*, PVLDB 2020  
  代码：https://github.com/megagonlabs/ditto  
  参考点：先生成候选实体对，再进行匹配判定，并注入领域知识。首版使用可解释的字段别名、设备实体和时间窗规则；后续可把 Ditto 或用户提供模型接入候选判定层。

### 嵌入式分析与融合（3.7）

- DuckDB, *An Embeddable Analytical Database*, SIGMOD 2019  
  论文与项目：https://duckdb.org/library/duckdb/  
  参考点：进程内分析、列式执行和直接查询 CSV/JSON/Parquet。首版为零依赖而使用 SQLite 与 Python 连接；数据规模扩大后可在保持 API 不变的情况下切换为 DuckDB/Arrow。

### 质量测试（3.6、3.8、3.9）

- Great Expectations Core  
  代码：https://github.com/great-expectations/great_expectations  
  参考点：把质量规则表达为可重复执行、可留证据的 Expectations。首版实现七维评分、格式适配器注册表和 JSON 自测报告。

## 外部代码接入要求

每次集成必须记录：

1. 论文名称、会议/期刊、论文链接；
2. 仓库 URL、许可证、固定 commit SHA；
3. 引入的源文件和本项目修改；
4. 模型权重来源、训练数据许可及下载方式；
5. 对 3.1–3.9 的影响、基准数据、硬件环境和回归结果。

不应在未确认许可证兼容性时直接复制 GPL/AGPL 代码到系统主体。模型代码、权重和大型依赖应放在 `integrations/` 的独立子目录，通过稳定接口调用。

## 公开基准与标准套件

以下资源实际进入 3.1–3.9 验收路径。固定文件指纹和选样协议见 `governance/benchmark_data/public/benchmark_manifest.json`。

### MetroPT-3

- UCI 数据页：https://archive.ics.uci.edu/dataset/791/metropt+3+dataset
- DOI：`10.24432/C5VW3R`
- 数据论文：Veloso et al., *The MetroPT dataset for predictive maintenance*, Scientific Data 2022, DOI `10.1038/s41597-022-01877-3`
- 选择理由：真实运营地铁空气生产单元的工业多变量时序，公开故障时间窗可同时支持压缩、对齐和融合验证。

### SECOM

- UCI 数据页：https://archive.ics.uci.edu/dataset/179/secom
- DOI：`10.24432/C54305`
- 选择理由：广泛使用的真实半导体制造过程数据，包含 590 个传感器字段和自然缺失值，适合关系存储及质量维度验证。

### NASA IMS Bearings

- NASA 数据页：https://data.nasa.gov/dataset/ims-bearings
- 选择理由：公开的真实轴承振动实验数据，原生 20 kHz 采样，适合验证高频文件回放和软件接收能力。

### HoloClean Hospital

- 论文：Rekatsinas et al., *HoloClean: Holistic Data Repairs with Probabilistic Inference*, PVLDB 2017
- 论文：https://www.vldb.org/pvldb/vol10/p1190-rekatsinas.pdf
- 仓库：https://github.com/HoloClean/holoclean
- 固定 commit：`d4f5929a8e4d92d4f41eb058c04c96cdcb0af767`
- 选择理由：数据清洗研究常用的真实关系数据基准，提供全单元格清洁真值，可独立核对关系数据错误而无需自行注入异常。

### JSONTestSuite

- 仓库：https://github.com/nst/JSONTestSuite
- 固定 commit：`1ef36fa01286573e846ac449e8683f8833c5b26a`
- 选择理由：RFC 8259 解析器广泛使用的符合性测试套件，文件名直接区分必须接受和必须拒绝的输入；行为未规定的 `i_` 用例不参与得分。

### W3C XML Conformance Test Suite

- 官方页面：https://www.w3.org/XML/Test/
- 固定版本：20130923
- 选择理由：W3C XML Core Working Group 发布的标准符合性套件，覆盖有效文档和非良构文档；测试仅选取不读取外部实体的二元用例以匹配安全解析策略。
