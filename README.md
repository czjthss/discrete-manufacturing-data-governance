# Discrete Manufacturing Data Governance

面向离散制造垂域模型的自动化数据治理系统。项目对应课题三里程碑2，提供一套零第三方 Python 依赖的可运行原型，覆盖序列数据与关系数据的存储压缩、解析、语义时序对齐、高频采集、质量稳控、按需融合、异构规范化和综合测评。

## 功能概览

- 3.1-3.9 每个指标对应一个独立 Python 文件，便于验收和后续替换。
- Web 前端提供运行总览、治理工作台、指标验证和技术集成视图。
- 后端提供自测、数据分析、融合演示、论文/代码集成元数据 API。
- 支持 CSV、TSV、JSON、JSONL、XML、INI 等输入规范化。
- 内置外部论文/GitHub 代码接入注册表，后续可挂载 CompressIoTDB、Apache TsFile、TsQuality、Matchmaker 等实现。
- 默认不复制第三方代码；外部实现必须确认许可证、固定 commit SHA，并通过 manifest 注册。

## 快速启动

```bash
cd code
python3 run.py
```

浏览器访问：

```text
http://127.0.0.1:8000
```

建议使用 Python 3.11 或更高版本。当前版本只使用 Python 标准库。

## 验证命令

```bash
cd code
python3 -m py_compile app.py run.py governance/*.py tests/test_indicators.py
python3 -m unittest discover -s tests
python3 -c "from app import run_all; r=run_all(); print(r['passed'], r['summary'])"
```

当前自测结果：

```text
21 tests OK
run_all: True {'total': 9, 'passed': 9, 'failed': 0}
```

## 指标映射

| 指标 | 文件 | 里程碑2实现 |
|---|---|---|
| 3.1 | `code/governance/indicator_3_1.py` | 序列与关系数据存储、压缩、回读 |
| 3.2 | `code/governance/indicator_3_2.py` | 有界误差 PLA 时序压缩，目标 9:1 |
| 3.3 | `code/governance/indicator_3_3.py` | 格式识别与结构解析，目标 >=95% |
| 3.4 | `code/governance/indicator_3_4.py` | 字段语义统一与时间窗对齐，目标 >=90% |
| 3.5 | `code/governance/indicator_3_5.py` | 批量环形缓冲采集，目标 1.1kHz |
| 3.6 | `code/governance/indicator_3_6.py` | 完整性、一致性、时效性、有效性 >=95% |
| 3.7 | `code/governance/indicator_3_7.py` | 序列数据与关系数据按需融合 |
| 3.8 | `code/governance/indicator_3_8.py` | 可扩展异构格式规范化测试框架 |
| 3.9 | `code/governance/indicator_3_9.py` | 七维工业数据质量综合测评 |

## Web API

- `GET /api/health`：服务健康检查。
- `GET /api/indicators`：指标清单、当前方法和计划接入项。
- `GET /api/integrations`：算法注册表、运行状态和 3.1-3.9 映射。
- `GET /api/references`：论文、仓库、许可证和 commit 元数据。
- `GET /api/report/latest`：最近一次自测报告。
- `POST /api/benchmark/all`：运行 3.1-3.9 全部自测。
- `POST /api/benchmark/{id}`：运行单项指标自测。
- `POST /api/analyze`：解析并治理用户输入数据。
- `POST /api/fusion/demo`：运行序列数据与工单关系融合演示。

## 外部论文与代码接入

核心入口在 `code/governance/integration_registry.py`，外部实现统一放在 `code/integrations/` 下。新增论文或 GitHub 代码时，建议创建独立目录并提供 `manifest.json`，结构参考：

```text
code/integrations/manifest.example.json
```

外部算法只有满足以下条件才可启用为 `active`：

- 代码许可证已确认且与项目使用方式兼容。
- 仓库 commit SHA 已固定。
- 算法 commit 与引用仓库 commit 一致。
- `entrypoint` 位于允许命名空间，例如 `integrations.xxx.adapter:ClassName`。
- 全部单元测试和 3.1-3.9 自测通过。

当前登记的待接入技术基座包括：

- CompressIoTDB, PVLDB 2025：压缩态查询、CompColumn、late decompression。
- Apache TsFile / IoTDB：工业时序列式存储、GORILLA/LZ4、设备/时间索引。
- TsQuality, VLDB 2023：completeness、consistency、timeliness、validity。
- Matchmaker, ICML 2025：零样本 schema matching 和自改进匹配程序。

详见 `code/REFERENCES.md` 和 `code/integrations/README.md`。

## 目录结构

```text
code/
  app.py                         # HTTP 服务与 API
  run.py                         # 启动入口
  governance/
    indicator_3_1.py             # 3.1
    ...
    indicator_3_9.py             # 3.9
    integration_registry.py      # 外部算法与论文代码注册表
  integrations/
    README.md
    manifest.example.json
  static/
    index.html
    app.js
    styles.css
  tests/
    test_indicators.py
```

## 验收说明

本系统输出的是工程自测证据，不等同于第三方检测结论。按照任务书口径，指标 3.6 在里程碑2正式验收时仍需由具有检测能力的第三方机构测试并提交报告。

压缩模块采用有界误差方法，报告会同时披露压缩比、误差界和最大重构误差。正式测试时需由评审通过的测试方案明确原始字节口径、数据集、误差容限、硬件环境和重复次数。
