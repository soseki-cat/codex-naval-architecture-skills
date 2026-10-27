# 验证、工具与交付

## 阶段证据与验收

| 证据层 | 需要记录 |
| -- | -- |
| 坐标 | 单位、源/目标参考轴、站位/半宽、高度、分段与结构/长度对应 |
| 几何质量 | 各类残差、区域均值、曲率/邻线、接缝、估计和REVIEW接受范围 |
| 拓扑 | 有效性、裸边/非流形、顶圈或闭合状态、法向、连接公差 |
| 保存 | 实际文件路径、对象/面数、原生回读、几何及保护比较 |

每项标明 `SOFTWARE_VERIFIED`、`USER_REPORTED` 或 `NOT_CHECKED`。历史JSON不是当前文件原生回读；没有实际观察不能报视觉检查通过；不能伪造 roundtrip=true 后宣称完成。

骨架任务停止于骨架验收并导出；水线任务停止于线网；下部封闭通常保留顶圈；完整外壳/甲板、有效拓扑、外向法向、几何质量接受与保存回读完成才标 `BASIC_HULL_COMPLETE`。该状态保留ESTIMATED、明确G0和既有REVIEW，不等于零残差、原船精准复刻、CFD或结构验收。

输出工作版、干净版、报告与必要图像；报告先列完成阶段和主要质量限制，再列数据/估计来源、方法及控制结构、残差/连续性、边界与法向、尺度、文件回读。定义模型B包围盒宽度、甲板宽度、舷边D、中心梁拱高度，避免混用。

## 坐标与残差工具

使用 `python <skill>/scripts/hull_math.py --input request.json [--output result.json]`，标准库，无Rhino依赖。输出文件必须是新JSON。请求为 `{"operation":"map_station","args":{...}}`；支持操作：

| operation | args |
| -- | -- |
| station_x | station, ap, fp, lbp_m, origin_station, confirmed=true |
| map_station | point, origin, width_axis, height_axis, x_m；可选mirror、metres_per_unit、plane_tolerance_m |
| map_bp | point, origin, length_axis, height_axis, y_m；可选x_reference_m、metres_per_unit、plane_tolerance_m |
| deduplicate | records=[{point:[x,y,z],source:...}], tolerance_m |
| residuals | records=[{distance_m,signed_half_width_m,x_m}], split_x_m=[艉舯界,舯艏界] |

轴为源图三维正交单位向量，单位换算只做一次。非平面源不压平；容差内法向分量保留。去重返回raw/unique/groups，所有源行和精度保留。残差工具只统计调用者已测量的数据，不计算NURBS距离，空数据返回未知而非0。

## Rhino 只读文件审计

`scripts/rhino_audit.py` 需在Rhino的Python运行时使用RhinoCommon，兼容IronPython2.7，不在普通Python或终端直接伪装运行。以RunPythonScript运行可选择审计配置JSON；自动化时加载模块后调用 `audit_files(config)`、`write_report(report,path)`。脚本只读取实际File3dm，不改当前文档/模型，不创建面、Save/Cap或改公差。

配置包含 `model_file`、`expected_units`（Rhino枚举字符串，如Meters）、`target_ids`（工作模型显式选最终壳体）、可选 `baseline_file`、`curve_roles`、`cuts` 和 `tolerance`（模型单位）。未指定target_ids时审计全部Brep，不从历史辅助面自动猜最终模型。

- curve_roles: `{id,kind:"ST"|"BP"|"WL",plane_value}`，按默认船体坐标检查固定X/Y/Z。用户采用其他目标轴约定时，不直接套用此角色检查；按用户坐标另做原生平面检查，并记录结果，不强改用户坐标。
- cuts: `{name,origin:[...],normal:[...],object_ids:[曲线GUID...]}`；真实CurvePlane事件保留参数/来源，重叠另报；无截点不是自动失败。
- 基线比较按同GUID几何CRC，记录缺失/变化/新增；干净模型没有原资料时不要要求它包含全部基线对象，基线保护在工作版验证。

审计报告实际backend为RhinoCommon.File3dm.Read，包含单位、目标有效性/闭合/法向、裸边/非流形、曲线平面、求交和基线比较。不会自动标BASIC_HULL_COMPLETE，视觉公平性和残差接受仍由当前任务检查。无法运行Rhino时保留NOT_CHECKED，不能用模拟JSON代替原生读取。

输出是新的独立JSON，不能覆盖输入模型/配置。ST/BP源点只读，无效单位或平面检查明确失败，不自动缩放、改点或填空。

## 原生 API 易错点

NURBS U/V不等于物理X/Z，读实际参数域。BrepFace.NormalAt包含面方向，不能重复按OrientationIsReversed反转；底层Surface.NormalAt另行处理方向。Surface.Transpose默认返回新面。File3dm对象表在某些运行时为可枚举集合，必要时转list读取。

文件SHA包含视图/属性；SHA变化时先检查几何CRC与实际输入版本，再决定是否为模型变化。保存后从真实文件回读，不能只检查未保存内存对象。绝对公差不随Join困难增大；连接/求交公差及模型单位都记录。
