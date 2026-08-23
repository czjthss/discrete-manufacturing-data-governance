# 逐指标测试入口

在 `code` 目录执行：

```bash
python3 run_indicator_tests.py 3.1
python3 run_indicator_tests.py 3.2
python3 run_indicator_tests.py 3.3
python3 run_indicator_tests.py 3.4
python3 run_indicator_tests.py 3.5
python3 run_indicator_tests.py 3.6
python3 run_indicator_tests.py 3.7
python3 run_indicator_tests.py 3.8
python3 run_indicator_tests.py 3.9
```

运行全部指标：

```bash
python3 run_indicator_tests.py all
```

每个 `test_indicator_3_x.py` 文件也可直接运行。例如：

```bash
python3 tests/individual/test_indicator_3_2.py
```

统一运行器默认在 `data/reports/indicator-tests/` 写入 JSON 报告，报告包括 Python 与操作系统信息、测试返回码、耗时和算法基准结果。使用 `--no-report` 可只执行测试，不写报告；使用 `--report-dir PATH` 可指定报告目录。

验收指标只读取 `governance/benchmark_data/public/benchmark_manifest.json` 登记并经 SHA-256 校验的公开真实数据或标准符合性套件。测试文件中的小型手写输入用于非法值、边界条件和安全性回归，不参与指标得分。

报告的 `source` 字段包含 Git 状态、逐文件 SHA-256 和组合源码哈希。固定交付包使用以下命令生成，包内 `PACKAGE_MANIFEST.json` 可用于逐文件校验：

```bash
python3 tools/build_delivery_package.py
```

算法文件、依赖文件、测试文件、运行命令及通过判据见 `algorithm_manifest.json`。完整测试大纲见 `docs/课题三指标3.1-3.9算法测试大纲与运行说明.md`。
