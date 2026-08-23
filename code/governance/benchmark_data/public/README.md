# 公开基准数据

本目录只存放验收测试实际读取的公开真实数据、标准符合性套件及其可复现清单。`benchmark_manifest.json` 记录来源、许可证、固定版本、选样协议、字节数和 SHA-256；`governance.public_benchmarks` 在每次加载前验证文件完整性。

## 数据集

### MetroPT-3

- 来源：UCI Machine Learning Repository，DOI `10.24432/C5VW3R`。
- 许可证：CC BY 4.0。
- 内容：真实运营地铁列车空气生产单元的压力、温度、电流及数字状态。
- 正式实验范围：官方归档全部 1,516,948 行和 15 个传感器通道。归档保存在被 Git 忽略的 `code/data/benchmark_cache`，运行时按清单中的 SHA-256 校验。
- 用途：3.1、3.2、3.3、3.4、3.5、3.6、3.7、3.8、3.9。

### SECOM

- 来源：UCI Machine Learning Repository，DOI `10.24432/C54305`。
- 许可证：CC BY 4.0。
- 内容：1,567 条半导体制造过程记录、590 个传感器字段、分类标签和时间戳；保留原始 `NaN` 缺失值。
- 用途：3.1、3.3、3.6、3.8、3.9。

### NASA IMS Bearings

- 来源：NASA Prognostics Center of Excellence / University of Cincinnati IMS Center。
- 许可证：United States Government Work。
- 固定文件：第二次实验的 `2004.02.12.10.32.39`，20,480 行、四通道、20 kHz。
- 用途：3.2 跨数据集压缩、3.5 原生频率与软件接收回放、3.6 和 3.9 序列质量补充结果。

### UCR FordA

- 来源：UCR Time Series Classification Archive，DOI `10.5281/zenodo.11191164`。
- 固定范围：TRAIN 与 TEST 两个官方分割全部 4,921 条等长序列，每条 500 点，共 2,460,500 个时序点。
- 用途：3.1、3.2、3.3、3.5、3.6、3.8、3.9。

### HoloClean Hospital

- 来源：HoloClean 官方仓库，固定 commit `d4f5929a8e4d92d4f41eb058c04c96cdcb0af767`。
- 许可证：Apache-2.0。
- 内容：1,000 行、19 列脏数据及 19,000 个单元格清洁真值。
- 用途：3.1、3.3、3.8、3.9。

### JSONTestSuite

- 来源：`nst/JSONTestSuite`，固定 commit `1ef36fa01286573e846ac449e8683f8833c5b26a`。
- 许可证：MIT。
- 固定范围：`test_parsing` 中全部 `y_` 和 `n_` 文件；`i_` 的行为由实现自行决定，因此不计分。
- 用途：3.3、3.8。

### W3C XML Conformance Test Suite

- 来源：W3C XML Core Working Group，20130923 版本。
- 固定范围：XMLTEST 目录中 `ENTITIES=none` 的 `valid` 和 `not-wf` 用例，共 301 个。
- 用途：3.8。符合性执行器按目录中的 `NAMESPACE` 元数据选择命名空间或非命名空间解析模式，并禁用外部实体。

## 复现

官方归档不直接由测试联网下载。准备者先从上方官方来源取得原始归档，再执行：

```bash
python3 tools/fetch_full_benchmarks.py
```

该命令只获取 3.2 使用的 MetroPT-3 官方完整归档，并验证来源清单登记的 SHA-256。重新构建其余固定公开文件时执行：

```bash
python3 tools/prepare_public_benchmarks.py \
  --metropt-archive /path/to/metropt3.zip \
  --secom-archive /path/to/secom.zip \
  --ims-file /path/to/2004.02.12.10.32.39 \
  --forda-train /path/to/FordA_TRAIN.ts \
  --forda-test /path/to/FordA_TEST.ts \
  --holoclean-dirty /path/to/hospital.csv \
  --holoclean-clean /path/to/hospital_clean.csv \
  --json-suite-archive /path/to/json-test-suite.tar.gz \
  --xml-suite-archive /path/to/xmlts20130923.zip
```

生成后核对 `benchmark_manifest.json`。选样规则在执行前固定，不按测试结果筛选；测试运行只读取清单登记的文件。

## 解释边界

- 公开数据可证明这些固定样本上的行为，不自动证明所有工厂、设备或数据分布。
- MetroPT-3 压缩覆盖官方完整 1,516,948 行和全部 15 个传感器通道，同时约束总体、最差数据块和最差通道压缩比，并逐值验证模拟量误差界与数字量无损回读。
- 3.5 只验证软件接收与缓冲区，不覆盖物理传感器、采集卡和网络。
- HoloClean 清洁真值用于测量输入数据本身的单元格准确率，不等同于自动修复算法的 precision、recall 或 F1。
