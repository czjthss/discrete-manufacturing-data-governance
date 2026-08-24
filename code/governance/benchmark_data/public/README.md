# 公开基准数据

`benchmark_manifest.json` 记录数据来源、许可证、固定版本、字节数和 SHA-256。`governance.public_benchmarks` 在加载前校验文件完整性。

## 正式实验数据

| 数据集 | 来源与范围 | 使用指标 |
|---|---|---|
| MetroPT-3 | UCI，DOI `10.24432/C5VW3R`，CC BY 4.0；完整 1,516,948 行、15 个传感器通道和 4 个维护区间 | 3.1-3.9 |
| UCR FordA | UCR Time Series Classification Archive，DOI `10.5281/zenodo.11191164`；TRAIN+TEST 全部 4,921 条序列 | 3.1、3.2、3.3、3.5、3.6、3.8、3.9 |
| UCI SECOM | UCI，DOI `10.24432/C54305`，CC BY 4.0；全部 1,567 条、590 个传感器字段和原始缺失值 | 3.1、3.3、3.6、3.8、3.9 |
| HoloClean Hospital | HoloClean 官方仓库 commit `d4f5929a8e4d92d4f41eb058c04c96cdcb0af767`，Apache-2.0；全部 1,000 行和 19,000 个清洁真值单元格 | 3.1、3.3、3.6、3.8、3.9 |

MetroPT-3 和 SECOM 是工业数据；FordA 是汽车系统时序基准；Hospital 是关系数据质量真值基准。当前正式指标结果只由这四套数据产生。

## 补充回归资产

目录还保留 NASA IMS Bearings、JSONTestSuite 和 W3C XML Conformance Test Suite，用于高频数据与通用解析器的补充回归。它们的版本和指纹同样记录在清单中，但不计入当前四数据集正式指标得分。

## 数据准备

MetroPT-3 官方完整归档不提交到 Git。下载并校验归档：

```bash
python3 tools/fetch_full_benchmarks.py
```

从官方归档重建清单登记文件时，先查看参数：

```bash
python3 tools/prepare_public_benchmarks.py --help
```

生成后应核对 `benchmark_manifest.json`。数据范围在运行前固定，不按实验结果筛选。

## 解释边界

- 公开基准只能证明固定版本和固定范围内的行为，不能自动外推至所有工厂、设备或数据分布。
- 3.2 覆盖 MetroPT-3 全部数据块与通道、FordA 全部序列，并同时约束总体和最差单元压缩比。
- 3.5 只评价软件接收与缓冲吞吐，不覆盖物理传感器、采集卡和网络链路。
- Hospital 真值用于评价输入关系数据的单元格准确率，不等同于自动修复算法的 precision、recall 或 F1。
