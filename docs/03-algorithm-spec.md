# 拼豆 3D 分件与卡扣算法规范

本规范是实现的权威算法基线。任何实现偏离都必须先更新本文件并写 ADR。

## 1. 输入与预处理

### 1.1 输入

- 同一物体的多视角图片，至少 3 张，建议 6–12 张。
- 豆规格：5mm 标准或 2.6mm 迷你。
- 可选：目标高度、最大板件尺寸 `Bmax`、色卡、背景去除开关。

### 1.2 图片校验

- MIME 与魔数一致：JPEG/PNG/WebP。
- 单张大小、总大小、分辨率上限可配置。
- 视角去重：感知哈希或特征匹配，避免重复图。
- 记录每张图的视角标签（front/back/left/right/top/bottom/unknown）。

## 2. 3D 重建

通过 Tripo 适配器提交多视角图片，轮询任务，下载 GLB 及纹理。

输出：

- `model.glb` 或 `model.obj`
- 纹理/材质
- 重建元数据（版本、耗时、输入图 ID）

失败策略：指数退避重试；超过上限进入 `failed`，保留错误码和可重试标记。

## 3. 实心体素化

### 3.1 归一化

1. 将模型统一到右手坐标系，`z` 向上。
2. 应用尺度，使一个体素边长等于 `bead_spec.pitch_mm`。
3. 将模型最低点对齐到 `z=0`，水平重心对齐到网格中心附近。
4. 记录变换矩阵，保证可逆。

M2-T1 实现位于 `apps/api/app/pipeline/normalization.py`：

- `load_glb_mesh` 读取 GLB/GLTF，并把 Scene 中的多个网格合并为一个 `Trimesh`。
- 默认按 glTF/Tripo 常见 Y-up 处理，绕 X 轴 +90° 转为 Z-up；也支持显式 `source_up_axis="z"`。
- 若提供 `target_height_mm`，按高度缩放到毫米；否则假设源单位已经是毫米。
- 网格尺寸使用 `ceil(extent_mm / pitch_mm - 1e-9)`，避免浮点误差多出一格。
- 归一化后模型包围盒为 `[0, width*pitch] × [0, height*pitch] × [0, depth*pitch]`。
- `transform` 为 4×4 齐次矩阵，可由 `NormalizedMesh.transform_point` 正向映射。

### 3.2 实心体素化

对网格做实心体素化，而不是只保留表面：

```text
V = { (x,y,z) | voxel center inside mesh }
```

实现建议：

- 先做保守/精确的三角形-体素相交，再用扫描线或泛洪填充内部。
- 对薄壁和孔洞做容差处理，避免漏填。
- 输出 `VoxelGrid`，并生成 `solid_mask` 预览。

M2-T1 实现确定性的**表面体素化** `surface_voxel_grid`，用于固定 GLB → 网格形状、变换矩阵和表面体素数量的黄金回归。M2-T2 在表面体素基础上实现 `solid_voxel_grid`：

- 从网格六个边界面出发，对空格做 6 邻域泛洪，标记与外部连通的体素。
- 其余体素视为实心，因此封闭空腔会被填充，贯穿孔洞会保留。
- 只有 `is_watertight` 且 `is_winding_consistent` 的网格才允许实心化；否则返回 `NORMALIZATION_NOT_WATERTIGHT`，不静默退化为表面结果。
- 黄金盒体样例：表面 134 个、内部 28 个、实心 162 个。

薄壁容差属于后续鲁棒性工作；颜色采样已在 M2-T3 实现。

### 3.3 颜色映射

1. 将纹理采样到体素中心。
2. 在选定色卡中做最近色匹配，使用 CIEDE2000 `ΔE`。
3. 允许 `ΔE <= tolerance` 的相近色合并；默认容差写入配置。
4. 输出 `color_by_voxel` 和每色颗数。

M2-T3 实现位于 `apps/api/app/pipeline/texture.py` 和 `apps/api/app/domain/color.py`：

- 对每个表面体素中心，用三角面质心 `cKDTree` 取候选面，再求最近三角面及其重心坐标；不依赖 `rtree`。
- 纹理网格在最近点的重心坐标处直接采样贴图，避免先采样顶点色再插值造成的 UV 接缝混色。UV 采用 glTF/trimesh 约定：图像行号对应 `1 - v`，越界按纹理尺寸取模。
- 没有纹理时支持顶点色；没有视觉数据时使用中性灰 `#666666`。
- 实心网格的内部体素通过最近表面体素的颜色传播，保证封闭空腔也有可复现色号。
- 色卡匹配使用 CIEDE2000；默认 Perler Standard 基线为 32 色近似值，`ΔE = 6.0`。项目色卡应允许后续配置覆盖，不能把近似基线冒充官方完整色卡。
- 颜色合并和体素遍历均使用稳定排序，输出 `color_by_voxel` 与 `color_counts()`。

稳定错误码：

| 错误码 | 含义 |
| --- | --- |
| `TEXTURE_GRID_MISMATCH` | 体素网格与归一化网格尺寸不一致 |
| `TEXTURE_INVALID_TOLERANCE` | `delta_e_tolerance` 为负数 |
| `TEXTURE_NO_SURFACE` | 模型没有可采样的表面体素 |
| `TEXTURE_DEGENERATE_MESH` | 没有有效三角面 |
| `TEXTURE_INVALID_TRIANGLES` | 三角面数组形状无效 |
| `TEXTURE_UV_MISSING` | 纹理视觉缺少 UV |
| `TEXTURE_UV_INVALID` | UV 数量、形状或数值无效 |
| `TEXTURE_IMAGE_MISSING` | 纹理视觉缺少贴图图像 |
| `TEXTURE_IMAGE_INVALID` | 贴图图像无法读取或格式无效 |
| `TEXTURE_VERTEX_COLOR_MISMATCH` | 顶点色数量与顶点数不一致 |
| `TEXTURE_VERTEX_COLOR_INVALID` | 顶点色形状或数值无效 |
| `TEXTURE_NO_TRIANGLE` | 体素中心找不到可采样三角面 |
| `TEXTURE_PALETTE_EMPTY` | 色卡为空 |

### 3.4 体素切片预览

M2-T4 在已着色的实心 `VoxelGrid` 上提供确定性 XY 切片审阅，不改变体素化结果：

1. 读取项目最新 `model_glb` 产物，按请求参数查找对应 `voxel_npz`；首次请求构建并持久化，后续命中缓存时直接读取。
2. `grid_shape = [width, height, depth]`，分别对应世界坐标 `x/y/z` 的格数。
3. 默认 `z = depth // 2`；显式 `z` 必须满足 `0 <= z < depth`，否则返回 `VOXEL_SLICE_OUT_OF_RANGE`。
4. 只返回 `voxel_z == z` 的实心格，按 `(x, y)` 稳定排序；每个格包含 `x`、`y`、色号 `color` 和十六进制 `hex`。
5. `grid_extent_mm`、`pitch_mm` 和 `slice_count` 来自归一化结果，前端不得自行推算物理尺寸。
6. 空切片合法返回 `occupied_count = 0` 和空 `cells`；没有 GLB 或 GLB 文件丢失时分别返回 `MODEL_ARTIFACT_NOT_FOUND` / `MODEL_ARTIFACT_MISSING`，不能用演示数据冒充真实结果。

坐标约定与体素索引一致：`x` 向右、`y` 向深度、`z` 向上；切片网格的行对应 `y`，列对应 `x`。前端只做显示和切片导航，不复制颜色匹配或实心化规则。

### 3.5 体素产物与缓存

M2-T5 将完整体素结果持久化为 `voxel_npz` 产物，避免预览切片和作业重试重复执行体素化：

- 产物 `kind = voxel_npz`，`content_type = application/octet-stream`，文件名为 `voxel_<cache_key>.npz`。
- 使用 `numpy.savez_compressed` 写入，读取时 `allow_pickle=False`；数组包含 `schema_version`、源模型 artifact ID/相对路径、采样参数、`pitch_mm`、`grid_shape`、`grid_extent_mm`、表面/内部体素数、`occupied_xyz`、`color_index`、`palette_ids` 和 `palette_hex`。
- artifact ID 为 `art_voxel_npz_<cache_key 前 24 位>`；缓存键由源模型 artifact ID、相对路径、`pitch_mm`、`target_height_mm`、`source_up_axis`、`delta_e_tolerance`、`palette_id` 和 schema 版本稳定哈希得到。
- 缓存记录存在且文件可读时直接复用；文件缺失、损坏或缓存键不匹配时重新构建并覆盖。体素化成功后才写入 artifact 记录，失败不会留下“成功”产物。
- `run_job` 在 `reconstruct` 后执行 `voxelize`。已有可用 `model_glb` 时复用模型，不重复调用 Tripo；体素化失败后重试只重跑 `voxelize`。M2 阶段完成后作业状态为 `succeeded`，`decompose` 及后续阶段保持 `queued`。

体素产物的稳定错误码：

| 错误码 | 含义 |
| --- | --- |
| `VOXEL_INVALID_TARGET_HEIGHT` | 目标高度不是正数 |
| `VOXEL_INVALID_TOLERANCE` | 色差容差为负数或非有限数 |
| `VOXEL_INVALID_UP_AXIS` | 上轴不是 `y` 或 `z` |
| `VOXEL_UNSUPPORTED_PALETTE` | 请求了不支持的色卡 |
| `VOXEL_ARTIFACT_MISSING` | 体素产物文件不存在 |
| `VOXEL_ARTIFACT_READ_FAILED` | NPZ 无法读取或内部结构损坏 |
| `VOXEL_ARTIFACT_WRITE_FAILED` | 体素产物无法写入 |
| `VOXEL_ARTIFACT_SCHEMA_UNSUPPORTED` | 产物 schema 版本不受支持 |
| `VOXEL_ARTIFACT_INVALID_GRID` | 网格尺寸无效 |
| `VOXEL_ARTIFACT_INVALID_PITCH` | 体素间距无效 |
| `VOXEL_ARTIFACT_INVALID_EXTENT` | 物理边界无效 |
| `VOXEL_ARTIFACT_INVALID_VOXEL` | 体素越界或重复 |
| `VOXEL_ARTIFACT_INVALID_COLOR_MAP` | 颜色索引/色号映射不一致 |

## 4. 层带与壳表示

### 4.1 水平层

对每个 `z`：

```text
L_z = { (x,y) | (x,y,z) in V }
```

M3-T1 实现位于 `apps/api/app/domain/layers.py`：

- `extract_horizontal_layers` 为每个 z 生成一个 `Layer`，包括空层；层号不被压缩，确保后续板件与装配坐标可追溯。
- 每层按 4 邻域 BFS 分解为 `LayerComponent`。对角相邻不算连通；分量按最小 `(y, x)` 稳定排序，ID 为 `L{z:03d}-C{index:03d}`。
- 边界格定义为至少一个 4 邻域不在该分量内的实体格；边界边只保留与空格相邻的单位轴对齐边，并按顺时针方向记录。
- 每个分量提供 `bounding_box()`、`width()`、`height()`、`area` 和 `color_counts()`，供 M3-T2 轮廓追踪和后续板件尺寸校验使用。
- 所有输出为整数格和单位边，不引入真曲面。

### 4.2 外轮廓

1. 提取 `L_z` 的 4-连通边界。
2. 将边界转换为方格边集合。
3. 追踪为闭合折线，允许孔洞（内轮廓）。
4. 用直线段简化；圆弧只能变成阶梯/折线，不能输出真曲线。

M3-T1 已提供第 1–2 步的确定性输入：`LayerComponent.boundary_edges` 是顺时针单位边集合，外轮廓和内孔均可由同一集合追踪。

M3-T2 实现位于 `apps/api/app/domain/contours.py`：

- 从每个分量的有向边界边出发，按“右转优先、直行、左转、掉头”的右手规则选择下一条边，直到回到起始格点；每个闭合环单独输出。
- 使用鞋带公式计算有向面积：正面积为外轮廓，负面积为内孔。一个 4-连通分量必须恰好有一个外轮廓；内孔按 `(min y, min x, id)` 稳定排序。
- 内孔取首条边的左侧半格点做点在多边形内校验，防止孔洞跑到外轮廓之外。
- `simplify_rectilinear_polygon` 只移除连续重复点和共线中间点，不新增顶点；简化前后都保持整数格顶点、闭合拓扑和孔洞数量。
- 输出 `Contour`、`ComponentContours`、`LayerContours` 和 `LayerContourExtraction`；`closed_vertices()` 提供显式闭合序列，便于后续 SVG/PDF 渲染。
- 所有轮廓边均为单位轴对齐边，不输出真曲线；M3-T3 已消费每层轮廓面积、孔数和颜色直方图做层带检测。

轮廓稳定错误码：

| 错误码 | 含义 |
| --- | --- |
| `CONTOUR_EMPTY_BOUNDARY` | 分量没有边界边 |
| `CONTOUR_OPEN_BOUNDARY` | 边界边无法闭合 |
| `CONTOUR_OUTER_COUNT_INVALID` | 4-连通分量不是恰好一个外轮廓 |
| `CONTOUR_DEGENERATE` | 轮廓面积为零或简化后坍缩 |
| `CONTOUR_HOLE_OUTSIDE` | 内孔不在外轮廓内 |
| `CONTOUR_INVALID_VERTICES` | 顶点数量、重复点或轴对齐不合法 |
| `CONTOUR_INVALID_SIMPLIFICATION` | 简化顶点不满足闭合折线不变量 |

### 4.3 层带检测

M3-T3 实现位于 `apps/api/app/domain/bands.py`。输入为 `LayerExtraction` 与 `LayerContourExtraction`，输出 `LayerBandExtraction`。

沿 `z` 计算相邻层的确定性指标：

- 颜色直方图距离：按层实体格数归一化，使用总变差距离；未着色格计入 `uncolored_fraction`，空层与实体层之间距离为 `1.0`。
- 外轮廓面积：每个分量 `outer.area` 之和；等效半径 `sqrt(outer_area / pi)`。
- 面积/半径变化：`abs(upper - lower) / max(upper, lower)`，两者均为零时记 `0.0`，结果限制在 `[0, 1]`。
- 孔洞数量变化与 4-连通分量数量变化：绝对差。

`LayerBandConfig` 显式保存五类阈值，默认颜色距离 `0.20`、面积变化 `0.10`、半径变化 `0.10`、孔数变化 `0`、分量数变化 `0`。只有指标严格大于阈值才切分；等于阈值不切分。空层与实体层之间固定以 `EMPTY_LAYER` 切分，连续空层合并为一个空层带。

层带按 z 连续覆盖，ID 为 `B01`、`B02`……；每个层带记录 `z_start`、`z_end`、`layer_indices`、`is_empty` 和进入该带的 `BandTransition`。`BandTransition` 保存上下层指标、颜色距离、面积/半径变化、孔数/分量数差值和稳定排序的切分原因。

层带稳定错误码：

| 错误码 | 含义 |
| --- | --- |
| `BAND_INVALID_CONFIG` | 阈值不是有限数、超出 `[0, 1]` 或计数为负 |
| `BAND_INVALID_GRID` | 层带提取的网格尺寸不是正数 |
| `BAND_GRID_MISMATCH` | 层提取与轮廓提取的网格尺寸不一致 |
| `BAND_COMPONENT_MISMATCH` | 同一 z 层的分量 ID 不一致 |
| `BAND_CONTOUR_MISMATCH` | 层实体格数与轮廓净面积不一致 |
| `BAND_INVALID_METRICS` | 层带指标不满足非负、有限或空层不变量 |
| `BAND_INVALID_TRANSITION` | 相邻层指标、差值或切分原因不合法 |
| `BAND_INVALID_BAND` | 层带 z 范围或入口 transition 不合法 |
| `BAND_INVALID_BANDS` | 层带未连续覆盖全部 z 或稳定 ID 不匹配 |
| `BAND_INVALID_TRANSITIONS` | 相邻层 transition 数量或 z 顺序不合法 |

### 4.4 水平板

```text
plate_cells = outer_contour - inner_holes
```

内孔来源：

1. 中心骨架截面。
2. 让围板舌穿过的让位。
3. 省豆减重孔。

输出环片/圆角方框，而不是实心片。

M3-T4 实现位于 `apps/api/app/domain/horizontal_plates.py`。输入为 `LayerExtraction`、`LayerContourExtraction` 和 `LayerBandExtraction`，输出 `HorizontalPlateExtraction`。

- 遍历每个非空层带的每个 z 层和 4-连通分量；空层带不产生记录。
- 用扫描线把外轮廓和内孔轮廓栅格化为整数格：在 `y + 0.5` 处求所有垂直边的交点并成对填充，因此结果与轮廓方向无关，且不会引入真曲面。
- 计算 `outer_cells - hole_cells`，必须与 `LayerComponent.cells` 完全一致；内孔必须位于外轮廓内，且不能与实体格或其他内孔重叠。
- 有内孔时生成 `PlateKind.RING` 板件：`cells` 使用分量实体格，`holes` 使用内孔格，颜色映射原样保留；板件必须 4-连通。
- 没有内孔时记录 `SkippedHorizontalComponent(reason=NO_INNER_HOLE)`，绝不生成水平实心片。
- 板件 ID 按层带、z 和分量顺序稳定为 `P01`、`P02`……；同一输入重跑结果完全一致。

水平环片稳定错误码：

| 错误码 | 含义 |
| --- | --- |
| `PLATE_INVALID_RECORD` | 记录 ID 为空、z 为负或孔轮廓 ID 不合法 |
| `PLATE_KIND_INVALID` | 水平板件不是 `RING` |
| `PLATE_SOLID_SLICE_FORBIDDEN` | 试图生成没有内孔的水平实心片 |
| `PLATE_DISCONNECTED` | 板件实体格不是 4-连通 |
| `PLATE_DUPLICATE_ID` | 板件 ID 重复 |
| `PLATE_BAND_MISMATCH` | 记录不属于存在的非空层带，或 z 超出层带范围 |
| `PLATE_DUPLICATE_COMPONENT` | 同一层带、z 和分量重复生成记录 |
| `PLATE_GRID_MISMATCH` | 层、轮廓和层带网格尺寸不一致 |
| `PLATE_COMPONENT_MISMATCH` | 层分量 ID 与轮廓分量 ID 不一致 |
| `PLATE_INVALID_CONTOUR` | 轮廓顶点不足、边不是轴对齐或扫描线交点不成对 |
| `PLATE_EMPTY_CONTOUR` | 轮廓栅格化后没有实体格 |
| `PLATE_HOLE_OUTSIDE` | 内孔位于外轮廓之外，或贴到外轮廓边界而只是缺口 |
| `PLATE_HOLE_OVERLAP` | 内孔与实体格重叠，或多个内孔互相重叠 |
| `PLATE_CONTOUR_MISMATCH` | 外轮廓减内孔后的格集合与分量实体格不一致 |

### 4.5 十字骨架

M3-T7 实现位于 `apps/api/app/domain/cross_skeletons.py`。输入为 `HorizontalPlateExtraction`，输出 `CrossSkeletonExtraction`。

- 每个水平环片只处理一个孔：取孔格按 4 邻域分解后的最大连通分量；大小相同时按最小格 `(y, x)` 稳定排序。
- 在孔的外接矩形中心生成加号形骨架：`arm_width_cells` 为奇数，默认 1；中心行和中心列各占 `arm_width_cells` 格。
- 孔的外接矩形在任一方向上的跨度必须至少为 `arm_width_cells + 2 * min_clearance_cells`，否则记录 `HOLE_TOO_SMALL`。
- 加号形骨架必须完全落在孔格内，否则记录 `HOLE_SHAPE_UNSUPPORTED`；不会把孔填实成水平实心片。
- 余量格 `clearance_cells = source_hole_cells - source_cells`，必须不少于 `min_clearance_cells`；它保留给 M4 的舌槽和可达性 BFS。
- 骨架板件 `PlateKind.CROSS_SKELETON` 的局部坐标平移到最小格为 `(0,0)`，必须 4-连通、无内孔；颜色取源孔位置在环片颜色映射中的值，缺失时允许为空。
- 板件 ID 按环片顺序稳定为 `P01`、`P02`……，可用 `start_plate_index` 与环片/围板编号错开。
- M3-T7 只生成单个十字空白件；M4-T1/T2 已生成候选描述符和真正的舌槽布尔，真正拆板与出图留给后续。

十字骨架稳定错误码：

| 错误码 | 含义 |
| --- | --- |
| `CROSS_INVALID_CONFIG` | 臂宽不是正奇数、余量格数为负或起始板件编号不是正整数 |
| `CROSS_INVALID_RECORD` | 记录 ID 为空、z 为负、孔轮廓 ID 不合法或源格为空 |
| `CROSS_KIND_INVALID` | 骨架板件不是 `CROSS_SKELETON` |
| `CROSS_HOLES_FORBIDDEN` | 骨架板件包含内孔 |
| `CROSS_DISCONNECTED` | 骨架实体格不是 4-连通 |
| `CROSS_DUPLICATE_ID` | 骨架板件 ID 重复 |
| `CROSS_DUPLICATE_RING` | 同一环片重复生成或同时跳过骨架 |
| `CROSS_PLATE_MISMATCH` | 骨架引用了不存在的水平环片 |
| `CROSS_BAND_MISMATCH` | 骨架 z 不属于非空层带 |
| `CROSS_CONTOUR_MISMATCH` | 骨架源格不是环片孔洞子集、余量格不守恒或孔轮廓 ID 不匹配 |

### 4.6 分解编排

M3-T7 的 `apps/api/app/domain/decomposition.py` 提供 `decompose_voxel_grid(grid, config)`，按固定顺序串联：

```text
水平层 -> 闭合轮廓 -> 层带 -> 水平环片 -> 垂直围板 -> 十字骨架 -> 板件接触图
```

`DecompositionExtraction` 保存每个阶段的完整结果，并校验所有子提取共享同一层带、水平板件和垂直板件。`fixtures/m3-decomposition.json` 固定 5×5×3 空心方管的 48 个体素、1 个层带、3 张 `RING`、4 张 `PERIMETER`、3 张 `CROSS_SKELETON`、20 条接触边和两组连通分量；黄金测试同时要求所有板件 4-连通、路线守卫通过和 `DesignValidator` 通过。

分解编排稳定错误码：

| 错误码 | 含义 |
| --- | --- |
| `DECOMPOSITION_BAND_MISMATCH` | 水平或垂直板件使用的层带与分解结果不一致 |
| `DECOMPOSITION_CROSS_MISMATCH` | 十字骨架使用的水平板件与分解结果不一致 |
| `DECOMPOSITION_ADJACENCY_MISMATCH` | 接触图使用的水平/垂直/十字骨架提取与分解结果不一致 |

## 5. 垂直围板

对外轮廓折线的每一段：

1. 取段长 `L` 和层带高度 `H`。
2. 摊成 `(u, v)` 矩形，`u ∈ [0, L)`，`v ∈ [0, H)`。
3. 以 `N=4–8` 段近似圆筒；每段是独立直片。
4. 在段两端预留接头位置。

围板不是弯片。曲率通过多段直片和阶梯折线表达。

M3-T5 实现位于 `apps/api/app/domain/vertical_plates.py`。输入为 `LayerExtraction`、`LayerContourExtraction` 和 `LayerBandExtraction`，输出 `VerticalPlateExtraction`。

- 只遍历非空层带；每个层带的代表层固定为 `source_z = z_start`，板件高度为 `band.layer_count`。空层带跳过。
- 每个代表层的 4-连通分量只使用外轮廓 `outer.simplified_vertices`；内孔不参与垂直围板，孔洞由 M3-T4 的水平环片处理。
- 简化轮廓必须闭合、轴对齐、无零长边，并且每条单位边都属于该分量的边界；简化面积必须与原始外轮廓一致且保持顺时针方向。
- 直边数少于 `min_segments` 时返回 `VERTICAL_SEGMENT_COUNT_INVALID`；直边数超过 `max_segments` 时按累计边长选择最接近等分的连续边边界，合并为 `N = max_segments` 段。每段至少包含一条直边。
- 每段生成一张 `PlateKind.PERIMETER` 板件：`width = sum(edge.length)`，`height = band.layer_count`，`cells = {(u, v) | 0 <= u < width, 0 <= v < height}`，`holes = frozenset()`。
- 每个 `u` 列的颜色取该单位边内侧实体格在代表层的颜色；缺失时回退到分量/层的稳定代表色。`v` 方向复制同一列颜色。
- `segment_index` 从 0 开始，`segment_count` 为 4–8；板件 ID 按层带、代表层、分量和段顺序稳定为 `P01`、`P02`……，可用 `start_plate_index` 与 M3-T4 的水平环片编号错开。
- `joint_margin_cells` 只记录段两端为 M4 舌槽预留的列；M3-T5 不挖槽，`joint_reserved_cells` 始终是板内实体格的子集。

垂直围板稳定错误码：

| 错误码 | 含义 |
| --- | --- |
| `VERTICAL_INVALID_CONFIG` | 段数不满足 4–8、预留格数为负或起始板件编号不是正整数 |
| `VERTICAL_GRID_MISMATCH` | 层、轮廓和层带网格尺寸不一致 |
| `VERTICAL_COMPONENT_MISMATCH` | 层分量 ID 与轮廓分量 ID 不一致 |
| `VERTICAL_INVALID_RECORD` | 记录 ID 为空、z/段索引非法、板件不是完整矩形或宽度短于起止跨度 |
| `VERTICAL_KIND_INVALID` | 垂直板件不是 `PERIMETER` |
| `VERTICAL_DISCONNECTED` | 板件实体格不是 4-连通 |
| `VERTICAL_DUPLICATE_ID` | 板件 ID 重复 |
| `VERTICAL_BAND_MISMATCH` | 记录不属于存在的非空层带、代表层不是 `z_start` 或高度不匹配 |
| `VERTICAL_SEGMENT_COUNT_INVALID` | 段数不足、段索引不连续或同一外轮廓段数不一致 |
| `VERTICAL_INVALID_CONTOUR` | 简化轮廓退化、非轴对齐、面积不一致、重复边界或无法对应实体格 |
| `VERTICAL_DUPLICATE_SEGMENT` | 同一外轮廓的同一段重复生成板件 |

## 6. 板件邻接图

```text
G = (P, E_contact)
```

- 节点 `P`：板件。
- 边 `E_contact`：两板存在物理接触面。

对每条边生成一对互补接头。接头候选必须记录：

- 接触边 `e`
- 法向 `dir`
- 沿边位置 `pos`
- 舌宽 `w`、舌长 `l`
- 类型：承力/销钉

M3-T6 实现位于 `apps/api/app/domain/plate_adjacency.py`。输入为 `LayerExtraction`、`LayerContourExtraction`、`HorizontalPlateExtraction`、`VerticalPlateExtraction` 和可选的 `CrossSkeletonExtraction`，输出 `PlateAdjacencyExtraction`。

- 只生成无向接触候选，不提前创建舌槽实体格；M4-T2 已在候选之上生成真正的舌槽布尔和 1 格余量。
- 节点是水平环片、垂直围板和十字骨架的板件 ID 并集。各提取必须使用相同网格和相同层带，且板件 ID 全局唯一。
- 接触来源四类：
  1. 同一层带、同一分量内，水平环片与外轮廓垂直围板接触。
  2. 同一外轮廓的相邻垂直段在共享竖直转角处形成 `SEGMENT_JOINT`。
  3. 相邻 z 层的水平板件在共享 XY 格上形成水平面接触。
  4. 相邻层带中起止顶点、段索引和段数一致的垂直围板形成跨层带垂直堆叠接触。
  5. 同一层带内相邻 z 的十字骨架在共享 XY 格上形成堆叠接触。
- 垂直围板的每个 `u` 列从来源简化轮廓逐边恢复内侧实体格，用于计算环片/围板和跨层带共享面积；恢复长度必须等于板件宽度。
- 边按规范板件 A/B、接触类型、法向、位置和来源描述稳定排序，ID 为 `E01`、`E02`……。`direction` 始终从 A 指向 B；`position` 是 A 板局部接触边上的起始格；`contact_length` 是沿边格数或共享面格数。
- 空设计合法：节点和边都为空，`connected_components()` 返回空元组。

板件邻接图稳定错误码：

| 错误码 | 含义 |
| --- | --- |
| `ADJACENCY_GRID_MISMATCH` | 层、轮廓和层带网格尺寸不一致 |
| `ADJACENCY_BAND_MISMATCH` | 水平与垂直板件使用的层带不一致 |
| `ADJACENCY_DUPLICATE_ID` | 水平与垂直板件 ID 重复 |
| `ADJACENCY_CONTOUR_MISMATCH` | 垂直板件的来源轮廓/分量/顶点无法恢复，或相邻段不连续 |
| `ADJACENCY_INVALID_CONTACT` | 接触边 ID、板件、类型、法向、位置或长度非法 |
| `ADJACENCY_INVALID_GRAPH` | 图节点包含空 ID |
| `ADJACENCY_UNKNOWN_PLATE` | 边引用了图中不存在的板件 |
| `ADJACENCY_DUPLICATE_EDGE` | 接触边 ID 或接触键重复且内容冲突 |
| `ADJACENCY_CROSS_MISMATCH` | 十字骨架提取与水平板件/层带不一致 |

## 7. 接头合成

### 7.1 候选生成（M4-T1）

M4-T1 实现位于 `apps/api/app/domain/joint_candidates.py`。输入为 `PlateAdjacencyExtraction`，输出 `JointCandidateExtraction`。

- 按接触边稳定顺序为每条边生成一个候选描述符，ID 为 `J01`、`J02`……；不创建舌实体格或槽空格。
- 候选记录接触边、规范板件 A/B、接触类型、从 A 指向 B 的法向、沿边居中起始位置、舌宽、舌长、槽余量、接头类型和来源接触长度。
- 接触边两端至少保留 `edge_margin_cells`（默认 1 格）；舌宽取 `load_bearing_width_cells`（默认 2）或 `pin_width_cells`（默认 1），并受 `available_width = contact_length - 2 * edge_margin_cells` 限制。
- 舌长取 `load_bearing_length_cells`（默认 3）或 `pin_length_cells`（默认 1）；槽宽/槽长分别为舌宽/舌长加 `slot_clearance_cells`（默认 1）。
- 居中位置 `position = (contact_length - width) // 2`；必须满足 `position >= edge_margin_cells` 且 `position + slot_width + edge_margin_cells <= contact_length`，否则记录 `CONTACT_TOO_SHORT`。
- Z 法向面接触（水平叠层、十字骨架堆叠）生成 1×1 销钉候选，位置固定为 0；其余接触按 `JointType` 选择承力或销钉尺寸。承力候选宽/长至少 2，销钉候选宽为 1、长不超过 2。
- 过短接触边不会静默降级为更小接头；`SkippedJointCandidate` 记录来源边、板件、接触类型、法向、接触长度、期望接头类型和 `CONTACT_TOO_SHORT`。
- 5×5×3 空心方管黄金样例生成 16 个候选（12 个环片/围板承力候选 + 2 个水平叠层销钉 + 2 个十字堆叠销钉）和 4 个垂直段接缝跳过；11×11×3 厚壁环生成 4 个 2×3 承力候选。

M4-T1 稳定错误码：

| 错误码 | 含义 |
| --- | --- |
| `JOINT_CANDIDATE_INVALID_CONFIG` | 余量/宽长/槽余量不满足范围，或承力/销钉尺寸非法 |
| `JOINT_CANDIDATE_INVALID_RECORD` | 候选或跳过记录的 ID、板件、枚举、位置、宽长或槽余量非法 |
| `JOINT_CANDIDATE_DUPLICATE_ID` | 候选 ID 重复 |
| `JOINT_CANDIDATE_DUPLICATE_EDGE` | 同一接触边重复生成候选或同时生成/跳过 |
| `JOINT_CANDIDATE_UNKNOWN_EDGE` | 候选或跳过记录引用了不存在的接触边 |
| `JOINT_CANDIDATE_EDGE_MISMATCH` | 候选/跳过记录的板件、类型、法向或接触长度与来源边不一致 |
| `JOINT_CANDIDATE_UNKNOWN_PLATE` | 按板查询时引用了图中不存在的板件 |

### 7.2 舌槽布尔（M4-T2）

M4-T2 实现位于 `apps/api/app/domain/joint_booleans.py`。输入为 `JointCandidateExtraction`，输出 `JointBooleanExtraction`。

- 以接触面建立局部 `(u,v,w)` 框架：`v` 从板 A 指向板 B，`u` 沿接触边，`w` 由右手定则确定。板件世界格先转换到该框架，再在接触行上放置舌和槽。
- 舌是板 A 上的一格厚凸舌；槽是板 B 上对应的贯穿空腔。槽可以延伸到板 B 实体格之外，用 `slot_air_cells` 表示真实贯穿开口，不能凭空增加第二层壁厚。
- 校验 `tongue_cells <= slot_cells`，且 `clearance_cells = slot_cells - tongue_cells` 至少 1 格；槽宽/槽长必须分别大于舌宽/舌长。
- 槽口必须位于接触边界：`slot_opening_cells` 是 `slot_solid_cells` 中位于接触起始行的格，至少 `min_slot_opening_cells` 格。
- 承力舌根至少 `min_root_depth_cells = 2` 格连入板 A 主片，销钉至少 `pin_root_depth_cells = 1` 格；壁深还必须至少容纳完整槽长，否则记录 `WALL_TOO_THIN`，不能静默缩短舌。
- 舌与板 B 挖槽后的剩余实体格必须不相交；`plate_intersection_cells` 必须为空。接触框架、槽口、余量、根深或板件类型不满足时，候选进入 `SkippedJointBoolean`，不生成半成品。
- 5×5×3 空心方管的 16 个候选全部因壁厚不足记录 `WALL_TOO_THIN`；7×7×3 环同样不可制造。11×11×1 厚壁环的 4 个候选全部生成完整布尔；11×11×3 厚壁环生成 12 个完整布尔，`J01`、`J06`、`J15`、`J16` 因壁厚不足跳过。
- M4-T2 不构造最终 `Joint`。槽口到板边界的全空格可达性 BFS 属于 M4-T3；所有板件统一采用双面有孔烫法，不区分轻烫区/重烫区，标记与孔保留校验属于 M4-T5。

M4-T2 稳定错误码：

| 错误码 | 含义 |
| --- | --- |
| `JOINT_BOOLEAN_INVALID_CONFIG` | 根深、槽口或布尔开关非法 |
| `JOINT_BOOLEAN_INVALID_RECORD` | 布尔或跳过记录的 ID、板件、枚举、坐标、格集合或接触框架非法 |
| `JOINT_BOOLEAN_DUPLICATE_ID` | 布尔 ID 重复 |
| `JOINT_BOOLEAN_DUPLICATE_CANDIDATE` | 同一候选重复生成布尔或同时生成/跳过 |
| `JOINT_BOOLEAN_UNKNOWN_CANDIDATE` | 布尔或跳过记录引用了不存在的候选 |
| `JOINT_BOOLEAN_CANDIDATE_MISMATCH` | 布尔的板件、类型、法向、宽长、余量或接触长度与来源候选不一致 |
| `JOINT_BOOLEAN_UNKNOWN_PLATE` | 按板查询时引用了图中不存在的板件 |

### 7.2.1 槽口可达性（M4-T3）

M4-T3 实现位于 `apps/api/app/domain/joint_reachability.py`。输入为 `JointBooleanExtraction`，输出 `JointReachabilityExtraction`。

- BFS 不在板件物理平面内，而在接触框架的槽腔平面 `u-v` 内固定厚度轴 `w`。板 B 剩余实体投影为障碍，槽腔和板外空间为自由格；这样垂直围板上的贯穿槽可以到达板外，而不会被误判为封闭内孔。
- 槽口投影必须全部位于板 B 的 4-邻域边界上；槽口格在槽腔平面内必须是自由格，否则记录 `SLOT_OPENING_NOT_ON_PLATE_BOUNDARY` 或 `UNSUPPORTED_PLATE`。
- 所需路径宽度为 `max(min_path_width_cells, boolean.width)`。在宽度 `w` 下，只有属于某个 `w×w` 全空格方块的格才可通行；对最大可达宽度做二分搜索，再从所有槽口格出发做 4-邻域 BFS，到达扩展后的板外边界。
- 返回路径并入槽口投影，保证 `opening_cells <= path_cells`；记录 `plate_axes`、`thickness_axis`、`thickness_value` 和最大 `path_width_cells`，所有坐标均为世界坐标整数格。
- 11×11×1 厚壁环的 4 个布尔全部可达，`J01` 固定为所需宽度 2、路径宽度 3、槽口 3 格；11×11×3 厚壁环的 12 个布尔全部可达，垂直贯穿槽 `J07`/`J11` 分别位于 `z=1`/`z=2` 的槽腔平面。配置宽度 4 时记录 `SLOT_OPENING_TOO_NARROW`，封闭孔记录 `NO_FREE_PATH_TO_PLATE_BOUNDARY`。
- 19 项领域测试覆盖配置/记录校验、薄厚壁黄金结果、垂直贯穿槽、按边/板查询、未处理布尔和稳定错误码。M4-T3 不构造最终 `Joint`；同边间距与防撕裂属于 M4-T4。

M4-T3 稳定错误码：

| 错误码 | 含义 |
| --- | --- |
| `JOINT_REACHABILITY_INVALID_CONFIG` | 最小路径宽度不是正整数 |
| `JOINT_REACHABILITY_INVALID_RECORD` | 可达/跳过记录的 ID、板件、宽度、轴、坐标或连通性非法 |
| `JOINT_REACHABILITY_DUPLICATE_ID` | 可达记录 ID 重复 |
| `JOINT_REACHABILITY_DUPLICATE_BOOLEAN` | 同一布尔同时生成可达和跳过记录，或重复处理 |
| `JOINT_REACHABILITY_UNKNOWN_BOOLEAN` | 可达/跳过记录引用了不存在的布尔 |
| `JOINT_REACHABILITY_BOOLEAN_MISMATCH` | 记录的板件、接触边、所需宽度或槽口与来源布尔不一致 |
| `JOINT_REACHABILITY_UNKNOWN_PLATE` | 按板查询时引用了图中不存在的板件 |

### 7.2.2 同边间距与防撕裂（M4-T4）

M4-T4 实现位于 `apps/api/app/domain/joint_spacing.py`。输入为 `JointReachabilityExtraction`，输出 `JointSpacingExtraction`。

- 每个接头同时投影为 A 侧舌 footprint `[position, position + width)` 和 B 侧槽 footprint `[slot_u_start, slot_u_start + slot_width)`；两侧都按 `(plate_id, contact_edge)` 分组检查，避免只检查舌件而漏掉共享槽件的同边冲突。
- 同一组内按 A 侧起点和稳定接头 ID 排序；先出现且满足规则的接头保留，后续冲突接头写入 `skipped`，不静默缩短、移动或改方向。
- 起点间距要求为 `max(left.width, right.width) + min_gap_cells`，默认 `min_gap_cells = 2`；两个槽体之间至少保留 1 格，不能相接或重叠。
- 槽 footprint 到接触边两端至少保留 `max(min_edge_margin_cells, boolean.edge_margin_cells)`，默认 `min_edge_margin_cells = 2`；边缘不足记录 `EDGE_MARGIN_INSUFFICIENT`。
- 返回 `previous_joint_id`/`next_joint_id`、A 侧起点间距、同边槽体间隔（按槽宽计算）和对应最小间距；B 侧冲突通过 `SkippedJointSpacing.plate_b`、`contact_edge` 和 `detail` 定位。
- 11×11×1 厚壁环的 4 个可达接头全部通过；11×11×3 厚壁环的 12 个可达接头全部通过。18 项领域测试覆盖 A/B 双侧同边、精确间距、间距不足、连续开槽、最大舌宽、边缘余量、配置/记录校验、重复/未知/元数据不匹配和空提取。
- M4-T4 不构造最终 `Joint`；所有板件统一采用双面有孔烫法，不区分轻烫区/重烫区，标记与孔保留校验属于 M4-T5。

M4-T4 稳定错误码：

| 错误码 | 含义 |
| --- | --- |
| `JOINT_SPACING_INVALID_CONFIG` | 间距或边缘余量不是至少 2 格的正整数 |
| `JOINT_SPACING_INVALID_RECORD` | 间距/跳过记录的 ID、板件、计数、邻居、原因或冲突 ID 非法 |
| `JOINT_SPACING_DUPLICATE_ID` | accepted 或 skipped 记录 ID 重复 |
| `JOINT_SPACING_DUPLICATE_REACHABILITY` | 同一可达接头同时 accepted 和 skipped |
| `JOINT_SPACING_UNKNOWN_REACHABILITY` | 记录引用了不存在的可达接头或来源布尔 |
| `JOINT_SPACING_REACHABILITY_MISMATCH` | 记录的板件、接触边、位置、宽长或余量与来源不一致 |
| `JOINT_SPACING_UNKNOWN_PLATE` | 按板查询时引用了图中不存在的板件 |

### 7.3 几何

舌 `T_j` 从 `p` 边外凸；槽 `S_j` 在 `q` 上挖空。

```text
T_j subset S_j
S_j \ T_j >= 1 格余量（宽度方向）
```

大型件默认：

- 插舌宽 2–3 格
- 插舌长 3–4 格
- 槽宽 = 舌宽 + 1
- 槽长 = 舌长 + 1

小件：

- 1 格细舌
- 1–2 格孔/槽
- 仅定位，不承力

### 7.4 放置

- 槽放在接触边中段，避开边缘至少 2 格。
- 同板同边两接头间隔 `>= w + 2`。
- 承力舌根部至少 2 格连主片。
- 销钉舌只用于小特征。

### 7.5 互补性

在全局坐标下：

- 舌实体格必须落在对方槽留空格内。
- 两板实体格不得相交。
- 槽至少比舌多 1 格余量。
- 不允许孤儿舌/槽。

### 7.6 可达性

从槽口到板边界做 BFS，具体实现见 7.2.1：

- 只走空格。
- 路径宽度至少 `max(配置值, 舌宽)`；宽度通过全空格 `w×w` 方块判定。
- 路径必须在接触框架的槽腔平面内到达扩展后的板外边界。
- 若被豆围死或槽口过窄，接头不可制造，必须换位置或改方向；记录稳定跳过原因，不静默降级。

### 7.7 双面有孔烫法

所有板件统一采用双面有孔烫法，不区分轻烫区/重烫区：

- 正反两面都只轻融到豆子边缘刚好粘合。
- 每颗豆中心孔完整保留，不烫成死平塑料板。
- 图纸只标记孔保留、槽口、装配顺序和风险说明，不生成轻/重烫分区。
- `RouteFeature.DOUBLE_SIDED_HOLE` 是所有设计输出的必需路线特征。

### 7.8 防撕裂

- 槽口到板边留至少 2 格。
- 同一接触边不要连续开槽。
- 大孔周围加 1 格加强环。

M4-T4 已把前两条实现为 `JointSpacingExtraction` 的硬门禁；大孔加强环属于后续板件几何增强，不在本任务中静默生成。

## 8. 装配 DAG 与自锁

### 8.1 顺序

边 `p -> q` 表示 `p` 必须先装。对全部接头求传递闭包：

- 不得成环。
- 若成环，翻转某个 `dir` 或改接头位置。
- 仍不行才输出“局部点胶”标注，且必须用户确认。

### 8.2 无胶自锁判据

全部满足才输出“免胶”：

1. **底环包重心**：底环外轮廓包住整体重心投影。
2. **三向接头**：至少 3 组法向互不平行（非共面）的接头。
3. **十字抗扭**：中心两片互补开槽板俯视成十字。
4. **唯一汇点**：装配 DAG 唯一汇点，且封顶方向为从上往下压合。

任一不满足，输出 `GLUE_FREE_SELF_LOCK_FAILED`，不得静默宣称免胶。

## 9. 2D 排版

### 9.1 局部网格

每板映射到 `(u, v)` 网格：

- `u` 沿边/弧长。
- `v` 沿高度或第二轴。
- 格色 = 体素色。

### 9.2 连通与切分

- 每板 4-连通。
- 不碎孤岛。
- 超过 `Bmax` 就切分，并补拼接舌。
- 切分后重新跑接头合成和 DAG。

### 9.3 平铺

- 全部板件塞进一张大网格。
- 板间至少 1 空行/空列。
- 同类相邻。
- 按装配序分行。
- 每板 1 格坐标框 + 编号。
- 槽：挖空 + 红框。
- 舌：凸出实体格。

### 9.4 图例

- 色号
- 每色颗数
- 板件编号
- 孔/槽/舌标记
- 孔保留标记
- 1:1 校验尺

## 10. 渲染与 PDF

### 10.1 展开网格图

- 主视图：逐板网格。
- 坐标：每 5 格标尺。
- 编号：`P01`。
- 色号：格内小字或图例。
- 孔槽：红框/阴影。

### 10.2 爆炸装配图

- 沿装配轴拉开。
- 插入箭头。
- 顺序号。
- 每步说明（“将 P02 从上方压入 P01”）。

### 10.3 成品三视图

- 前/上/侧。
- 核对朝向、层次、孔洞。

### 10.4 PDF

- A4/A3 可选。
- 1:1 打印校验尺。
- 页眉：项目名、豆规格、日期。
- 页脚：页码、版本、路线守卫状态。
- 字体嵌入，中文可打印。

## 11. 校验器门禁

出图前必须全部通过：

| 门禁 | 错误码 |
| --- | --- |
| 每板 4-连通 | `PLATE_DISCONNECTED` |
| 不超板 | `PLATE_OVERSIZE` |
| 接头一一配对 | `JOINT_ORPHAN` |
| 舌槽互补 | `JOINT_NOT_COMPLEMENTARY` |
| 槽可达边界 | `JOINT_UNREACHABLE` |
| 同边间距 | `JOINT_SPACING_VIOLATION` |
| 装配 DAG 无环 | `ASSEMBLY_CYCLE` |
| 唯一汇点 | `ASSEMBLY_NO_UNIQUE_SINK` |
| 重心投影在底环内 | `COM_OUTSIDE_BOTTOM_RING` |
| 双面有孔烫法已应用 | `ROUTE_REQUIRED_FEATURE_MISSING`（`double_sided_hole`） |
| 色号在色卡 | `COLOR_NOT_IN_PALETTE` |
| 路线合规 | `ROUTE_*` |

## 12. 退化兜底

| 情况 | 处理 |
| --- | --- |
| 曲面 | 阶梯/折线近似 |
| 悬空细长特征 | 销钉贴片 + 1 格支撑舌 |
| 内部实心 | 空心环片省豆 |
| 接头成环 | 改方向/位置 |
| 仍无法免胶 | 显式 `local_glue` 标注，用户确认 |

## 13. 确定性与性能

- 所有排序使用稳定键：`(z, y, x, id)`。
- 随机采样固定种子。
- 浮点容差集中配置，不散落。
- 初始性能目标：256³ 体素化 < 30s；100 板分件 < 60s；PDF < 30s。
- M2-T5 基准（开发机，5mm 豆，256³ 盒体）：归一化 0.005s、表面体素化 1.983s、实心填充 17.837s，总计 19.825s，满足 30s 预算。
- 该基准只覆盖归一化、表面体素化和实心填充，不含完整颜色采样；完整 128³ 着色体素化目前约 86s，颜色传播与色卡匹配优化归入 M7-T4。

## 14. 实现顺序

严格按 `docs/05-implementation-plan.md` 的 M1–M7 推进。不要先做漂亮渲染再补可制造性；领域门禁优先。
