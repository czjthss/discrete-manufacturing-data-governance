# 课题组时序压缩实现

本目录保存课题组最新时间序列压缩成果的多语言实现，覆盖 REGER、BOS 和 TS_2DIFF+BOS。

## 目录

- `backend/myapp/reger_codec.py`：REGER Int64/Float64 Python 核心实现。
- `backend/myapp/iotdb_style_python.py`：BOS、TS_2DIFF 及相关编码研究实现。
- `cpp/src/`：REGER、BOS、TS_2DIFF+BOS C++ 实现。
- `java/src/main/java/org/example/`：REGER、BOS、TS_2DIFF+BOS Java 实现与基准入口。

系统运行入口位于 `code/integrations/group_research/adapter.py`。适配器负责输入边界、有限数值、int64 范围、载荷完整性和往返一致性检查；指标 3.2 记录各算法压缩率与最大误差。

该目录属于项目研究代码。对外发布或与第三方项目组合前，应补充课题组确认的著作权与许可证文件。
