# 论文与开源代码集成区

本目录承载项目自有论文方法适配器及经审核的外部论文实现。核心注册表位于
`governance/integration_registry.py`，网页通过 `/api/integrations` 和
`/api/references` 展示集成状态。

## 接入流程

1. 为外部实现创建独立目录，例如 `integrations/compress_iotdb/`。
2. 在该目录放置 `manifest.json`，结构参考 `manifest.example.json`。
3. 记录论文、仓库、许可证、固定 commit SHA、模型权重和本地修改。
4. 编写薄适配器，使外部代码满足本项目稳定接口。
5. 许可证与 commit 核实后，将算法状态从 `planned` 改为 `active`，并填写
   `entrypoint`，例如 `integrations.compress_iotdb.adapter:CompressIoTDBCodec`。
6. 运行全部单元测试和 3.1–3.9 自测，记录基准数据及硬件环境。

注册表启动时会自动发现 `integrations/*/manifest.json`。只有状态为 `active`
且配置了有效 `entrypoint` 的算法才能通过 `IntegrationRegistry.resolve()` 加载；
计划项不会导入可选依赖，因此不会破坏当前零第三方依赖运行能力。

## 已启用适配器

- `group_research/adapter.py`：已有成果 REGER、BOS 与 TS_2DIFF+BOS 的统一接口。
- `research_methods/adapter.py`：压缩态查询、Schema Matching 和窗口质量计算的项目自有实现。

注册表会解析每个 active 入口，并在适配器提供 `healthcheck()` 时执行功能检查。配置可运行与运行时可用是两个独立状态。

## 稳定接口

- 压缩：`compress(values, tolerance) -> bytes`，`decompress(payload)`。
- 压缩态查询：`query_compressed(payload, operation, arguments)`。
- 数据解析：输入文本或字节流，输出 `list[dict]`。
- Schema matching：`match(source_schema, target_schema, context)`。
- 对齐：输入序列记录、关系记录和时间容差，输出带对齐证据的记录。
- 质量：返回 0–100 分的命名质量维度，可选窗口参数。
- 融合：输入两类规范化记录，输出融合结果与吞吐量统计。

## 合规门槛

在许可证和 commit SHA 未确认前，必须保持 `status: planned`，不得复制源代码或
启用运行入口。论文许可与代码许可需要分别核对；论文可公开阅读不代表仓库代码
可直接嵌入。GPL/AGPL 或自定义非商业许可证需要单独评估与系统主体的兼容性。

每次接入至少记录：

- 论文名称、会议/期刊、论文链接；
- 仓库 URL、代码许可证和固定 commit SHA；
- 引入文件、本地修改和补丁；
- 模型权重来源、训练数据许可与校验值；
- 对应的 3.1–3.9 指标、测试数据、硬件环境和回归结果。
