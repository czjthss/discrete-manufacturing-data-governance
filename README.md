# Discrete Manufacturing Data Governance

面向离散制造垂域模型的自动化数据治理系统。系统提供序列数据与关系数据的存储压缩、结构解析、语义时序对齐、高频采集、质量稳控、按需融合、异构规范化、综合测评及可审计治理工作台。

## 能力范围

- 3.1–3.7：里程碑2核心能力，包括存储压缩、9:1 时序压缩、95% 解析、90% 对齐、1.1kHz 采集、四维质量稳控和序列/关系融合。
- 3.8–3.9：后续阶段预研能力，包括异构数据规范化测试框架和七维工业数据质量综合测评。
- 每个指标对应 `code/governance/indicator_3_x.py` 独立文件。
- 每次测试与治理请求使用独立标识和产物目录，报告采用原子替换写入。
- 工作台支持规则配置、确定性修复、异常隔离、质量前后对比、血缘记录和报告下载。
- 外部代码须确认许可证并固定 commit SHA 后才能启用；项目自有方法适配器与外部官方代码状态分别记录。

## 课题组压缩成果

`reger_bos_code_paths/` 保存课题组最新成果的 Python、C++ 和 Java 实现，系统通过 `code/integrations/group_research/adapter.py` 提供统一运行接口：

- REGER Int64：分块重排、残差建模和分段位宽编码。
- REGER Float64：浮点位模式映射和无损恢复。
- BOS Int64：分块差分、ZigZag 和变长整数编码。
- TS_2DIFF+BOS Int64：在二阶差分与 BOS 之间按载荷大小自适应选择。
- TS_2DIFF+BOS Float：十进制定点映射与自适应压缩。

指标 3.2 会对上述实现执行独立压缩、解压、往返一致性、压缩率和最大误差测量。注册表中的运行状态来自真实入口解析和健康检查。

## 快速启动

```bash
cd code
python3 run.py
```

浏览器访问 `http://127.0.0.1:8000`。建议使用 Python 3.11 或更高版本，默认运行路径仅依赖 Python 标准库。

## 验证命令

```bash
PYTHONPATH=code python3 -m py_compile code/app.py code/run.py code/governance/*.py code/integrations/*/*.py
PYTHONPATH=code python3 -m unittest discover -s code/tests -v
PYTHONPATH=code python3 -c "from app import run_all; r=run_all(); print(r['passed'], r['summary'])"
```

当前回归基线：29 项单元与对抗测试通过，9 项指标自测通过。并发测试同时执行 24 个 `run_all()`，逐项验证报告路径唯一且 JSON 可重新读取。

## 指标映射

| 指标 | 范围 | 文件 | 实现与口径 |
|---|---|---|---|
| 3.1 | 里程碑2核心 | `code/governance/indicator_3_1.py` | 序列/关系存储、原子压缩备份、往返回读 |
| 3.2 | 里程碑2核心 | `code/governance/indicator_3_2.py` | 有界误差 PLA 及课题组 REGER/BOS/TS_2DIFF+BOS |
| 3.3 | 里程碑2核心 | `code/governance/indicator_3_3.py` | 六类格式、独立标注样例、异常拒绝、95% Wilson 区间 |
| 3.4 | 里程碑2核心 | `code/governance/indicator_3_4.py` | 字段归一、实体匹配、精确时间窗优先，目标不低于 90% |
| 3.5 | 里程碑2核心 | `code/governance/indicator_3_5.py` | 重复吞吐测量、最低速率和零丢失检查，目标 1.1kHz |
| 3.6 | 里程碑2核心 | `code/governance/indicator_3_6.py` | 完整性、一致性、相对当前时刻的时效性、有效性 |
| 3.7 | 里程碑2核心 | `code/governance/indicator_3_7.py` | 序列数据与工单关系按需融合 |
| 3.8 | 后续阶段预研 | `code/governance/indicator_3_8.py` | 可扩展规范化适配器和标注结果验证 |
| 3.9 | 后续阶段预研 | `code/governance/indicator_3_9.py` | 七维测评、主数据外键检查和分设备稳定性 |

## 技术适配

系统提供三个项目自有、可运行的论文方法适配器：

- CompressIoTDB 方法适配器：块级最值裁剪、候选块延迟解压和压缩态范围过滤。
- TsQuality 方法适配器：按事件时间窗口计算 completeness、consistency、timeliness、validity。
- Matchmaker 方法适配器：Schema 候选生成、别名精炼、置信度评分和拒绝阈值。

这些适配器采用公开方法思想实现，未复制尚未完成许可证与版本核验的外部仓库代码。Apache TsFile、CompressIoTDB 官方仓库、TsQuality 附属源码和 Matchmaker 官方代码仍按各自元数据状态管理。详见 `code/REFERENCES.md` 与 `code/integrations/README.md`。

## Web API

- `GET /api/health`：服务健康检查。
- `GET /api/indicators`：指标、范围和方法映射。
- `GET /api/integrations`：算法配置状态与运行时检查。
- `GET /api/references`：论文、仓库、许可证和版本元数据。
- `GET /api/report/latest`：最近一次指标自测报告。
- `GET /api/reports`：报告目录。
- `GET /api/reports/download/{name}`：下载指定报告。
- `POST /api/benchmark/all`：运行 3.1–3.9 全部自测。
- `POST /api/benchmark/{id}`：运行单项指标自测。
- `POST /api/analyze`：解析、清洗、隔离、测评、存储并记录血缘。
- `POST /api/rules/validate`：校验治理规则。
- `POST /api/fusion/demo`：运行序列数据与工单关系融合演示。

## 目录结构

```text
code/
  app.py
  governance/
    indicator_3_1.py ... indicator_3_9.py
    integration_registry.py
    pipeline.py
  integrations/
    group_research/adapter.py
    research_methods/adapter.py
  static/
  tests/
reger_bos_code_paths/
  backend/myapp/reger_codec.py
  cpp/src/
  java/src/main/java/org/example/
```

## 验收说明

系统报告属于工程自测证据，不等同于第三方检测结论。指标 3.6 在里程碑2正式验收时仍需由具有检测能力的第三方机构测试并提交报告。

正式测试方案应固定数据集版本、原始字节口径、误差容限、主数据快照、硬件环境、重复次数和统计区间。自测报告已经记录 Python、操作系统、处理器、进程标识、运行标识和每项测量结果，便于复核与复现。
