# 领域模型与不变量

## 1. 单位与坐标

- 物理尺寸统一用毫米 `mm`。
- 体素/板件格统一用整数。
- 世界坐标：`x` 向右、`y` 向深度、`z` 向上。
- 体素索引 `(x, y, z)` 满足 `0 <= x < width`、`0 <= y < height`、`0 <= z < depth`。
- 板件局部坐标 `(u, v)`：`u` 沿边/弧长方向，`v` 沿高度或第二轴。
- 体素中心用于重心计算：`(x + 0.5, y + 0.5, z + 0.5)`。

## 2. 聚合关系

```text
Project 1---1 BeadSpec
Project 1---* SourceImage
Project 1---1 Design
Design 1---1 VoxelGrid
Design 1---* Plate
Design 1---* Joint
Design 1---1 AssemblyGraph
Design 1---1 ValidationReport
Job 1---* StageRun
Project 1---* Artifact
```

## 3. 核心实体

### `BeadSpec`

单颗拼豆的物理规格。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `size` | `5mm \| 2.6mm` | 豆规格 |
| `outer_diameter_mm` | float | 外径 |
| `pitch_mm` | float | 格距/体素边长 |
| `height_mm` | float | 管长 |
| `hole_diameter_mm` | float | 内孔径 |
| `board_max_cells_x/y` | int | 单板最大格数 |

不变量：所有尺寸为正；孔径小于外径；板限为正。

### `VoxelGrid`

实心体素集合与颜色。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `width/height/depth` | int | 网格尺寸 |
| `occupied` | `frozenset[(x,y,z)]` | 实心体素 |
| `color_by_voxel` | `dict[(x,y,z), color_id]` | 体素色号 |

不变量：所有 occupied 在边界内；颜色键必须是 occupied 子集。

### `BoundaryEdge`

整数格上的有向单位边。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `start` | `(x, y)` | 起点格点 |
| `end` | `(x, y)` | 终点格点，必须与起点相差一个单位轴 |

边按屏幕坐标（`x` 向右、`y` 向下）顺时针围绕实体格发出；相邻实体格共享的内部边不输出。外轮廓与内孔都可由该边集合追踪，且不会产生真曲线。

### `LayerComponent`

一个水平层内的 4-连通实体分量。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | str | 稳定 ID，如 `L003-C001` |
| `z` | int | 层索引 |
| `cells` | `frozenset[(x,y)]` | 分量实体格 |
| `color_by_cell` | `dict[(x,y), color_id]` | 格色 |
| `boundary_cells` | `frozenset[(x,y)]` | 至少一个 4 邻域为空的实体格 |
| `boundary_edges` | `tuple[BoundaryEdge, ...]` | 与空格相邻的单位边界边 |

不变量：非空；颜色键是 cells 子集；边界格/边必须由 cells 精确推导；cells 必须 4-连通。

### `Layer`

单个 `z` 水平层。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `z` | int | 层索引 |
| `cells` | `frozenset[(x,y)]` | 层实体格，可为空 |
| `color_by_cell` | `dict[(x,y), color_id]` | 格色 |
| `components` | `tuple[LayerComponent, ...]` | 4-连通分量 |
| `boundary_cells` | `frozenset[(x,y)]` | 分量边界格并集 |
| `boundary_edges` | `tuple[BoundaryEdge, ...]` | 分量边界边并集 |

不变量：components 必须恰好划分 cells；空层合法；边界字段必须与 components 一致。

### `LayerExtraction`

整个体素网格的水平层提取结果。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `width/height/depth` | int | 体素网格尺寸 |
| `layers` | `tuple[Layer, ...]` | 每个 z 一个层，包含空层 |

不变量：`len(layers) == depth`；层 z 从 0 连续到 `depth-1`；分量和边界边按 `(z, y, x)` 稳定排序。

### `ContourKind`

闭合轮廓类型：

- `outer`：实体外轮廓，屏幕坐标下顺时针。
- `hole`：内部孔洞，屏幕坐标下逆时针。

### `Contour`

一个闭合的整数格折线。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | str | 稳定 ID，如 `L003-C001-O` / `L003-C001-H001` |
| `z` | int | 层索引 |
| `component_id` | str | 所属 4-连通分量 |
| `kind` | `ContourKind` | 外轮廓或内孔 |
| `vertices` | `tuple[(x,y), ...]` | 未重复闭合点的整数格顶点 |
| `simplified_vertices` | `tuple[(x,y), ...]` | 去除重复/共线点后的整数格顶点 |

不变量：至少 4 个顶点；不重复首尾；无连续重复点；面积非零；外轮廓 `area2 > 0`，内孔 `area2 < 0`。`closed_vertices()` 返回追加首点的闭合序列。

### `ComponentContours`

一个 4-连通分量的全部轮廓。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `component_id` | str | 分量 ID |
| `z` | int | 层索引 |
| `outer` | `Contour` | 唯一外轮廓 |
| `holes` | `tuple[Contour, ...]` | 内孔，按 `(min y, min x, id)` 稳定排序 |

不变量：外轮廓必须为 `outer`，内孔必须为 `hole`；所有轮廓属于同一分量和层；内孔位于外轮廓内；ID 唯一。

### `LayerContours`

单个水平层的轮廓集合。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `z` | int | 层索引 |
| `components` | `tuple[ComponentContours, ...]` | 分量轮廓 |

不变量：components 的 z 必须与层一致；component ID 唯一；`area` 为外轮廓面积减内孔面积。

### `LayerContourExtraction`

整个体素网格的层轮廓提取结果。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `width/height/depth` | int | 体素网格尺寸 |
| `layers` | `tuple[LayerContours, ...]` | 每个 z 一个轮廓层，包含空层 |

不变量：`len(layers) == depth`；层 z 从 0 连续到 `depth-1`；轮廓和孔洞计数稳定可复现。

### `LayerBandConfig`

层带切分阈值。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `color_distance_threshold` | float | 0.20 | 颜色直方图总变差距离阈值 |
| `area_change_threshold` | float | 0.10 | 外轮廓面积相对变化阈值 |
| `radius_change_threshold` | float | 0.10 | 等效半径相对变化阈值 |
| `hole_count_change_threshold` | int | 0 | 孔洞数量绝对变化阈值 |
| `component_count_change_threshold` | int | 0 | 4-连通分量数量绝对变化阈值 |

不变量：浮点阈值必须是有限数且位于 `[0, 1]`；计数阈值必须为非负整数；测量值严格大于阈值才切分。

### `LayerBandMetrics`

单个 z 层的层带指标。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `z` | int | 层索引 |
| `cell_count` | int | 实体格数，可为 0 |
| `outer_area` | float | 所有分量外轮廓面积之和 |
| `equivalent_radius` | float | `sqrt(outer_area / pi)` |
| `hole_count` | int | 内孔总数 |
| `component_count` | int | 4-连通分量数 |
| `color_histogram` | `dict[color_id, float]` | 按实体格数归一化的颜色占比 |

不变量：空层面积/半径/孔数/分量数均为 0 且直方图为空；非空层外轮廓面积和分量数为正；分量数不超过实体格数；颜色占比有限且总和不超过 1。

### `BandTransition`

相邻两层之间的层带指标与切分原因。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `lower/upper` | `LayerBandMetrics` | 相邻下层/上层指标 |
| `color_distance` | float | 颜色直方图总变差距离，`[0, 1]` |
| `area_change` | float | 外轮廓面积相对变化，`[0, 1]` |
| `radius_change` | float | 等效半径相对变化，`[0, 1]` |
| `hole_count_delta` | int | 孔洞数量绝对变化 |
| `component_count_delta` | int | 分量数量绝对变化 |
| `reasons` | `tuple[BandSplitReason, ...]` | 去重并按枚举顺序稳定排序 |

`BandSplitReason` 取值：`empty_layer`、`component_count_change`、`hole_count_change`、`color_distance`、`area_change`、`radius_change`。不变量：上下层 z 连续；所有指标有限且范围合法；差值必须与上下层指标一致。

### `LayerBand`

连续 z 范围组成的层带。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | str | 稳定 ID，如 `B01` |
| `z_start/z_end` | int | 闭区间 z 范围 |
| `is_empty` | bool | 该带是否全部为空层 |
| `transition` | `BandTransition \| None` | 进入该带的切分 transition；首个带为 `None` |

不变量：z 范围非负且有序；非首个带必须有包含切分原因的入口 transition，且 transition 的上层 z 等于 `z_start`。

### `LayerBandExtraction`

整个体素网格的层带提取结果。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `width/height/depth` | int | 体素网格尺寸 |
| `bands` | `tuple[LayerBand, ...]` | 连续覆盖全部 z 的层带 |
| `transitions` | `tuple[BandTransition, ...]` | 每个相邻 z 对一条，长度 `depth - 1` |

不变量：层带按 `B01`、`B02`……稳定编号并恰好覆盖 `0..depth-1`；transition 按 z 连续排序；每个新层带的入口 transition 必须是对应相邻层的切分 transition。

### `HorizontalPlateSkipReason`

水平环片提取的跳过原因。当前只有 `NO_INNER_HOLE`：该 4-连通分量没有内孔，不能生成水平实心片。

### `HorizontalPlate`

一个由层带、z 层和 4-连通分量生成的 `RING` 水平板件记录。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `plate` | `Plate` | 实际板件，`kind` 必须为 `ring` |
| `band_id` | str | 来源层带 ID，如 `B01` |
| `z` | int | 来源层索引 |
| `component_id` | str | 来源 4-连通分量 ID |
| `outer_contour_id` | str | 外轮廓 ID |
| `hole_contour_ids` | `tuple[str, ...]` | 内孔轮廓 ID，按稳定顺序排列 |

不变量：板件必须有至少一个内孔且 4-连通；`hole_contour_ids` 非空、唯一，且数量不能超过 `plate.holes` 的格数（一个内孔轮廓可以包含多个空格）。无孔分量不得伪造为水平实心片。

### `SkippedHorizontalComponent`

没有生成水平环片的分量记录，包含 `band_id`、`z`、`component_id`、`outer_contour_id` 和 `reason`。当前 `reason` 固定为 `NO_INNER_HOLE`。

### `HorizontalPlateExtraction`

整个体素网格的水平环片提取结果。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `bands` | `LayerBandExtraction` | 输入层带 |
| `plates` | `tuple[HorizontalPlate, ...]` | 生成的环片，按稳定顺序排列 |
| `skipped` | `tuple[SkippedHorizontalComponent, ...]` | 无内孔而跳过的分量 |

不变量：板件 ID 唯一；每条记录必须属于一个存在的非空层带；同一层带、z 和分量最多生成一条记录；同一分量不能同时出现在 `plates` 和 `skipped`。空层带不产生记录。

### `VerticalPlateConfig`

垂直围板的分段配置。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `min_segments` | int | 4 | 每段外轮廓至少拆成几张直片 |
| `max_segments` | int | 8 | 每段外轮廓最多拆成几张直片 |
| `joint_margin_cells` | int | 2 | 段两端为 M4 舌槽预留的格数 |

不变量：`4 <= min_segments <= max_segments <= 8`；`joint_margin_cells >= 0`。配置只记录预留区，不在 M3-T5 中挖槽。

### `VerticalPlate`

一张由外轮廓直边区间摊成的 `PERIMETER` 垂直直片记录。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `plate` | `Plate` | 实际板件，`kind` 必须为 `perimeter` |
| `band_id` | str | 来源层带 ID，如 `B01` |
| `component_id` | str | 来源 4-连通分量 ID |
| `source_z` | int | 代表层索引，等于层带 `z_start` |
| `contour_id` | str | 来源外轮廓 ID |
| `segment_index` | int | 从 0 开始的段索引 |
| `segment_count` | int | 该外轮廓的段数，范围 4–8 |
| `start_vertex` | `(x, y)` | 区间的水平轮廓起点 |
| `end_vertex` | `(x, y)` | 区间的水平轮廓终点 |
| `joint_margin_cells` | int | 两端接头预留格数 |

不变量：板件为从 `(0,0)` 开始的完整矩形、4-连通、无内孔；`segment_index` 从 0 连续到 `segment_count - 1`；`plate.height()` 等于层带层数；板件宽度不小于起止顶点的曼哈顿距离。`joint_reserved_cells` 只返回板内两端预留列，不修改实体格。

### `VerticalPlateExtraction`

整个体素网格的垂直围板提取结果。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `bands` | `LayerBandExtraction` | 输入层带 |
| `plates` | `tuple[VerticalPlate, ...]` | 生成的围板，按层带、代表层、分量和段顺序排列 |

不变量：板件 ID 唯一；每条记录属于存在的非空层带；同一外轮廓的段索引完整且连续；同一段最多生成一张板；记录高度必须匹配层带高度。空层带不产生记录。

### `CrossSkeletonConfig`

十字骨架空白件的配置。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `arm_width_cells` | int | 1 | 加号形骨架的臂宽，必须为正奇数以保留唯一中心 |
| `min_clearance_cells` | int | 1 | 骨架与孔壁之间至少保留的余量格数 |

不变量：`arm_width_cells` 为正奇数；`min_clearance_cells >= 0`。M3-T7 只生成单个十字空白件，M4-T1/T2 已生成候选描述符和舌槽布尔，真正拆板与出图留给后续。

### `CrossSkeleton`

从水平环片孔内生成的一张 `CROSS_SKELETON` 加号形空白件。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `plate` | `Plate` | 实际板件，`kind` 必须为 `cross_skeleton` |
| `band_id` | str | 来源层带 ID，如 `B01` |
| `z` | int | 来源层索引 |
| `component_id` | str | 来源 4-连通分量 ID |
| `hole_contour_ids` | `tuple[str, ...]` | 选中的内孔轮廓 ID |
| `source_hole_cells` | `frozenset[(x,y)]` | 源层带坐标下的整个孔格 |
| `source_cells` | `frozenset[(x,y)]` | 源层带坐标下的加号形骨架格 |
| `clearance_cells` | `frozenset[(x,y)]` | 孔内未被骨架占用的余量格 |
| `arm_width_cells` | int | 实际使用的臂宽 |

不变量：板件无内孔且 4-连通；`source_cells <= source_hole_cells`；`clearance_cells == source_hole_cells - source_cells`；`plate.cells` 是 `source_cells` 平移到最小坐标为 `(0,0)` 的局部网格。颜色当前取源孔位置在环片颜色映射中的值，孔内无颜色时允许为空，M4/M5 再显式分配材料。

### `SkippedCrossSkeleton`

无法生成十字骨架时的显式跳过记录。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `band_id` | str | 来源层带 ID |
| `z` | int | 来源层索引 |
| `component_id` | str | 来源 4-连通分量 ID |
| `hole_contour_ids` | `tuple[str, ...]` | 选中的内孔轮廓 ID |
| `reason` | enum | `hole_too_small \| hole_shape_unsupported` |

不变量：同一层带、z 和分量不能同时出现在 `plates` 与 `skipped` 中。

### `CrossSkeletonExtraction`

整个体素网格的十字骨架提取结果。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `horizontal` | `HorizontalPlateExtraction` | 输入水平环片 |
| `plates` | `tuple[CrossSkeleton, ...]` | 生成的十字骨架，按环片顺序排列 |
| `skipped` | `tuple[SkippedCrossSkeleton, ...]` | 无法生成的环片记录 |

方法：`plates_in_band`、`plates_at_z`、`plate_by_id`。不变量：板件 ID 唯一；每条记录必须引用存在的水平环片；骨架源孔必须是该环片孔洞的子集；孔轮廓 ID 必须属于该环片。

### `DecompositionConfig`

M3 分解配置聚合。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `band` | `LayerBandConfig` | 默认阈值 | 层带检测配置 |
| `vertical` | `VerticalPlateConfig` | 4–8 段 | 垂直围板配置 |
| `cross_skeleton` | `CrossSkeletonConfig` | 1 格臂宽 | 十字骨架配置 |

### `DecompositionExtraction`

一次完整 M3 分解结果，串联层、轮廓、层带、水平环片、垂直围板、十字骨架和接触图。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `layers` | `LayerExtraction` | 水平层 |
| `contours` | `LayerContourExtraction` | 闭合轮廓 |
| `bands` | `LayerBandExtraction` | 层带 |
| `horizontal` | `HorizontalPlateExtraction` | 水平环片 |
| `vertical` | `VerticalPlateExtraction` | 垂直围板 |
| `cross_skeletons` | `CrossSkeletonExtraction` | 十字骨架 |
| `adjacency` | `PlateAdjacencyExtraction` | 板件接触图 |

属性：`plates` 按水平、垂直、十字骨架顺序拼接；`contact_edges` 返回接触边；`plates_by_kind` 和 `plate_by_id` 提供查询。不变量：所有子提取必须共享同一层带、水平板件和垂直板件；接触图必须使用同一十字骨架提取。`decompose_voxel_grid(grid, config)` 是确定性入口。

### `PlateContactKind`

板件接触类型。

- `FACE`：两板共享轴对齐接触面，包括水平叠层、跨层带垂直堆叠和环片/围板接触。
- `SEGMENT_JOINT`：同一外轮廓的相邻垂直直片在竖直转角处相接，需要 M4 生成转角互锁。

### `PlateContactEdge`

无向接触图中的一条边。`plate_a` 始终按字典序小于 `plate_b`，`direction` 表示从 A 指向 B 的接触法向。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | str | 稳定 ID，如 `E01` |
| `plate_a/plate_b` | str | 规范排序后的两块板件 |
| `kind` | `PlateContactKind` | `face \| segment_joint` |
| `direction` | `JointDirection` | 从 A 指向 B 的轴对齐法向 |
| `position` | int | 在 A 板局部接触边上的起始格位置 |
| `contact_length` | int | 沿接触边的格数；水平面接触时为共享格数 |
| `contact_edge` | str | 可追溯的层带/轮廓/段来源描述 |
| `band_id/source_z` | `str \| None` / `int \| None` | 来源层带和代表层 |
| `contour_id/segment_index` | `str \| None` / `int \| None` | 来源外轮廓和垂直段索引 |
| `joint_type_hint` | `JointType` | M4 接头类型提示，当前为承力接头 |

不变量：两板不同且 ID 非空；`plate_a < plate_b`；位置非负；接触长度为正；法向和类型必须是枚举值。M3-T6 不包含舌实体格、槽空格或轻/重烫分区。

### `PlateContactGraph`

无向板件接触图 `G=(P,E_contact)`。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `nodes` | `frozenset[str]` | 板件 ID 集合 |
| `edges` | `tuple[PlateContactEdge, ...]` | 去重并按板件 ID、类型、法向、位置稳定排序的接触边 |

方法：`neighbors`、`edges_for`、`degree`、`has_edge`、`contact_length`、`connected_components`、`is_connected`。空图合法，`connected_components()` 返回空元组。

### `PlateAdjacencyExtraction`

板件邻接提取结果，包含输入的水平/垂直板件提取、可选的十字骨架提取和生成的 `PlateContactGraph`。不变量：图节点必须与水平环片、垂直围板和十字骨架的板件 ID 集合完全一致；M3-T7 起接触图包含十字骨架同层带相邻 z 的堆叠接触。

### `JointCandidateConfig`

接头候选的尺寸规则。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `edge_margin_cells` | int | 1 | 接触边两端至少保留的格数 |
| `load_bearing_width_cells` | int | 2 | 承力舌宽，至少 2 |
| `load_bearing_length_cells` | int | 3 | 承力舌长，至少 2 |
| `pin_width_cells` | int | 1 | 销钉舌宽，必须为 1 |
| `pin_length_cells` | int | 1 | 销钉舌长，1–2 |
| `min_width_cells` / `max_width_cells` | int | 1 / 3 | 舌宽范围 |
| `min_length_cells` / `max_length_cells` | int | 1 / 4 | 舌长范围 |
| `slot_clearance_cells` | int | 1 | 槽比舌宽/舌长多出的余量，至少 1 |

不变量：所有计数为非负整数；承力宽/长至少 2；销钉宽为 1、长为 1–2；默认值必须落在最小/最大范围内。

### `JointCandidate`

一条接触边上的舌槽描述符，不包含实体格。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | str | 稳定 ID，如 `J01` |
| `contact_edge_id` | str | 来源接触边 ID，如 `E01` |
| `plate_a/plate_b` | str | 规范排序后的两块板件 |
| `contact_kind` | `PlateContactKind` | `face \| segment_joint` |
| `direction` | `JointDirection` | 从 A 指向 B 的接触法向 |
| `position` | int | 沿接触边的起始格，居中放置 |
| `width` | int | 舌宽（沿接触边） |
| `length` | int | 舌长（垂直接触边） |
| `joint_type` | `JointType` | `load_bearing \| pin` |
| `slot_clearance_cells` | int | 槽余量 |
| `contact_length` | int | 来源接触边长度 |
| `edge_margin_cells` | int | 来源配置的两端余量 |

属性：`slot_width = width + slot_clearance_cells`，`slot_length = length + slot_clearance_cells`。不变量：两板不同且按 ID 规范排序；位置非负；宽/长/余量/接触长度为正；Z 法向面接触必须是 1×1 销钉且位置为 0；承力候选宽/长至少 2；销钉候选宽为 1、长不超过 2；舌和槽都必须落在接触边内并保留两端余量。

### `SkippedJointCandidate`

无法生成候选的接触边记录。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `contact_edge_id` | str | 来源接触边 ID |
| `plate_a/plate_b` | str | 规范排序后的两块板件 |
| `contact_kind` | `PlateContactKind` | 接触类型 |
| `direction` | `JointDirection` | 接触法向 |
| `contact_length` | int | 接触边长度 |
| `joint_type` | `JointType` | 期望的接头类型 |
| `reason` | enum | 当前为 `contact_too_short` |

### `JointCandidateExtraction`

接头候选提取结果。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `adjacency` | `PlateAdjacencyExtraction` | 来源接触图及其板件提取 |
| `candidates` | `tuple[JointCandidate, ...]` | 生成的候选，按接触边顺序排列 |
| `skipped` | `tuple[SkippedJointCandidate, ...]` | 无法生成的接触边 |

属性/方法：`graph`、`candidate_count`、`skipped_count`、`unhandled_edges`、`candidate_by_id`、`candidates_for_edge`、`skipped_for_edge`、`candidates_for_plate`。不变量：候选 ID 唯一；每条接触边最多一个候选或一个跳过记录；候选的板件、类型、法向和接触长度必须与来源边一致；未知板件查询返回 `JOINT_CANDIDATE_UNKNOWN_PLATE`。M4-T1 只生成描述符，不创建舌实体格或槽空格。

### `JointBooleanConfig`

M4-T2 舌槽布尔的可制造性阈值。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `min_root_depth_cells` | int | 2 | 承力舌根至少连入主片的格数 |
| `pin_root_depth_cells` | int | 1 | 销钉舌根至少连入主片的格数 |
| `min_slot_opening_cells` | int | 1 | 槽口在接触边界上的最小开口格数 |
| `require_wall_depth_cells` | bool | true | 是否要求壁厚至少容纳完整槽长 |
| `allow_slot_air_cells` | bool | true | 是否允许槽延伸到板 B 实体格之外，以表示贯穿开口 |

不变量：根深度至少 2 格（承力）或 1 格（销钉）；槽口至少 1 格；两个布尔开关必须是 `bool`。

### `JointBoolean`

一个 M4-T1 候选对应的真实舌实体格与槽留空格。所有格集合均为世界坐标 `(x,y,z)`。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` / `candidate_id` | str | 与候选一致的稳定 ID，如 `J01` |
| `contact_edge_id` | str | 来源接触边 ID |
| `plate_a/plate_b` | str | 舌件/槽件 |
| `contact_kind` / `direction` | enum | 接触类型和从 A 指向 B 的法向 |
| `position/width/length` | int | 沿边位置、舌宽、舌长 |
| `joint_type` | `JointType` | `load_bearing \| pin` |
| `tongue_cells` | `frozenset[Coord3]` | 板 A 上的一格厚舌实体格 |
| `slot_cells` | `frozenset[Coord3]` | 板 B 上要挖掉的槽格 |
| `tongue_root_cells` | `frozenset[Coord3]` | 舌根连入板 A 主片的格 |
| `slot_opening_cells` | `frozenset[Coord3]` | 位于接触边界、构成槽口的格 |
| `slot_solid_cells` | `frozenset[Coord3]` | 槽与板 B 实体格的交集 |
| `slot_air_cells` | `frozenset[Coord3]` | 槽伸出板 B 实体格的部分 |
| `plate_b_remaining_cells` | `frozenset[Coord3]` | 挖槽后板 B 剩余实体格 |
| `plate_intersection_cells` | `frozenset[Coord3]` | 舌与剩余板 B 实体的交集，必须为空 |
| `u_axis/v_axis/w_axis` | `Coord3` | 右手正交接触框架 |
| `contact_w` / `v_origin` | int | 接触行与槽起始深度 |
| `slot_u_start` | int | 槽沿边起始位置 |
| `wall_depth_cells` | int | 板 A 在舌根方向的可用壁深 |
| `root_depth_cells` | int | 实际舌根深度 |
| `required_root_depth_cells` | int | 接头类型要求的根深度 |

属性：`slot_width`、`slot_length`、`clearance_cells = slot_cells - tongue_cells`、`tongue_cell_count`、`slot_cell_count`、`clearance_count`、`is_complementary`。不变量：舌非空且是槽的子集；余量非空；槽口是槽实体格的子集；舌与板 B 剩余实体不相交；根深度不超过壁深且满足接头类型要求；三个轴构成右手正交框架。

### `SkippedJointBoolean`

无法制造为完整舌槽布尔的候选记录，包含候选/接触边/板件/接触类型/法向/接触长度/接头类型和稳定 `reason`。跳过原因包括 `WALL_TOO_THIN`、`SLOT_NOT_OPEN_TO_BOUNDARY`、`PLATE_INTERSECTION`、`TONGUE_ROOT_TOO_SHORT`、`CLEARANCE_INSUFFICIENT`、`CONTACT_FRAME_INVALID` 和 `UNSUPPORTED_PLATE`。

### `JointBooleanExtraction`

M4-T2 布尔结果及其消费的 M4-T1 候选。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `candidates` | `JointCandidateExtraction` | 来源候选提取 |
| `booleans` | `tuple[JointBoolean, ...]` | 成功生成的完整舌槽布尔 |
| `skipped` | `tuple[SkippedJointBoolean, ...]` | 不可制造候选 |

属性/方法：`graph`、`source`、`candidate_extraction`、`boolean_count`、`skipped_count`、`unhandled_candidates`、`candidate_by_id`、`boolean_by_id`、`booleans_for_edge`、`skipped_for_edge`、`booleans_for_plate`。不变量：布尔 ID 唯一；每个候选最多生成一个布尔或一个跳过记录；布尔的板件、类型、法向、位置、宽长、余量和接触长度必须与来源候选一致。所有板件统一采用双面有孔烫法，不区分轻烫区/重烫区；M4-T2 不构造最终 `Joint`。

### `JointReachabilityConfig`

M4-T3 槽口可达性的可制造性阈值。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `min_path_width_cells` | int | 1 | 槽口到板边界的最小自由路径宽度 |

不变量：必须是正整数。实际要求宽度为 `max(min_path_width_cells, boolean.width)`；在宽度 `w` 下，只有属于某个 `w×w` 全空格方块的格才可通行。

### `JointReachability`

一个完整 M4-T2 布尔对应的槽口可达路径。所有格集合均为世界坐标 `(x,y,z)`。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `boolean_id` | str | 与来源布尔一致的稳定 ID，如 `J01` |
| `candidate_id` / `contact_edge_id` | str | 来源候选和接触边 |
| `plate_a/plate_b` | str | 舌件/槽件 |
| `required_width_cells` | int | `max(配置值, 舌宽)` |
| `path_width_cells` | int | 二分搜索得到的最大可达路径宽度 |
| `path_cells` | `frozenset[Coord3]` | 从槽口到板外边界的 4-连通自由路径 |
| `opening_cells` | `frozenset[Coord3]` | 投影后的槽口格，必须包含在 `path_cells` 中 |
| `plate_axes` | `tuple[int, int]` | BFS 使用的两个世界轴，即接触框架的 `u/v` 轴 |
| `thickness_axis` | int | 接触框架 `w` 轴对应的世界轴 |
| `thickness_value` | int | 槽腔平面固定的 `w` 坐标 |

属性：`id`、`is_reachable`。不变量：ID 和板件合法；路径/槽口非空；槽口是路径子集；所有格位于固定厚度平面；路径在 `plate_axes` 投影上 4-连通；`path_width_cells >= required_width_cells`。

### `SkippedJointReachability`

无法到达板外空间的完整布尔记录，包含布尔/候选/接触边/板件、`required_width_cells`、`max_path_width_cells` 和稳定 `reason`。跳过原因包括 `SLOT_OPENING_NOT_ON_PLATE_BOUNDARY`、`SLOT_OPENING_TOO_NARROW`、`NO_FREE_PATH_TO_PLATE_BOUNDARY`、`PATH_TOO_NARROW` 和 `UNSUPPORTED_PLATE`。`max_path_width_cells` 必须是非负整数。

### `JointReachabilityExtraction`

M4-T3 可达性结果及其消费的 M4-T2 布尔。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `booleans` | `JointBooleanExtraction` | 来源布尔提取 |
| `reachable` | `tuple[JointReachability, ...]` | 可达的完整布尔 |
| `skipped` | `tuple[SkippedJointReachability, ...]` | 不可达或不可制造的布尔 |

属性/方法：`graph`、`source`、`boolean_extraction`、`reachable_count`、`skipped_count`、`unhandled_booleans`、`reachability_by_id`、`reachable_for_edge`、`skipped_for_edge`、`reachable_for_plate`。不变量：可达记录 ID 唯一；每个布尔最多生成一个可达或跳过记录；记录元数据必须与来源布尔一致；未知板件查询返回 `JOINT_REACHABILITY_UNKNOWN_PLATE`。M4-T3 只验证可达性，不构造最终 `Joint`。

### `JointSpacingConfig`

M4-T4 同板同边间距与防撕裂阈值。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `min_gap_cells` | int | 2 | 两接头起点之间除舌宽外至少保留的格数，必须至少为 2 |
| `min_edge_margin_cells` | int | 2 | 槽 footprint 到接触边两端至少保留的格数，必须至少为 2 |

不变量：两个字段都是正整数且不小于 2。实际起点间距为 `max(left.width, right.width) + min_gap_cells`；实际边缘余量为 `max(min_edge_margin_cells, boolean.edge_margin_cells)`。

### `JointSpacing`

一个通过同板同边间距和边缘余量检查的可达接头。`plate_id` 是舌件 A；`previous_joint_id`/`next_joint_id` 和对应的 gap 字段表示 A 侧同边相邻关系。B 侧槽位也参与冲突检查；`slot_gap_*` 记录同一对相邻接头在槽侧的间隔，不在本记录中重复保存 B 侧邻接链。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `reachability` | `JointReachability` | 来源可达记录 |
| `boolean` | `JointBoolean` | 来源舌槽布尔 |
| `plate_id` | str | 舌件 A 的板件 ID |
| `contact_edge` | str | 接触边来源标签 |
| `previous_joint_id` / `next_joint_id` | str \| None | A 侧同边相邻接头 |
| `gap_before_cells` / `gap_after_cells` | int \| None | A 侧起点间距 |
| `slot_gap_before_cells` / `slot_gap_after_cells` | int \| None | 同边槽体间隔（按槽宽计算） |
| `required_gap_before_cells` / `required_gap_after_cells` | int \| None | 对应方向的最小起点间距 |

不变量：包装的可达记录和布尔元数据一致；`plate_id == reachability.plate_a`；相邻 ID 非空且不等于自身；有邻居时 gap 非负、`gap >= required_gap` 且 `slot_gap >= 1`。

### `SkippedJointSpacing`

无法满足同边间距或边缘余量的可达接头记录，包含布尔/候选/接触边/板件、位置、舌宽、槽宽、接触长度、边缘余量、`required_gap_cells`、`actual_gap_cells`、`slot_gap_cells`、稳定 `reason` 和可选 `conflict_joint_id`。跳过原因包括 `SPACING_TOO_NARROW`、`CONTINUOUS_SLOT`、`EDGE_MARGIN_INSUFFICIENT` 和保留的 `UNSUPPORTED_EDGE`。所有计数必须是非负整数，`required_gap_cells` 必须为正。

### `JointSpacingExtraction`

M4-T4 间距结果及其消费的 M4-T3 可达性。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `reachability` | `JointReachabilityExtraction` | 来源可达性提取 |
| `accepted` | `tuple[JointSpacing, ...]` | 通过间距和边缘余量的接头 |
| `skipped` | `tuple[SkippedJointSpacing, ...]` | 间距不足、连续开槽或边缘余量不足的接头 |

属性/方法：`graph`、`source`、`reachability_extraction`、`accepted_count`、`skipped_count`、`source_skipped`、`unhandled_reachable`、`spacing_by_id`、`accepted_for_edge`、`skipped_for_edge`、`accepted_for_plate`、`skipped_for_plate`。不变量：accepted/skipped ID 唯一；同一可达接头不能同时 accepted 和 skipped；记录元数据必须与来源可达记录和布尔一致；未知板件查询返回 `JOINT_SPACING_UNKNOWN_PLATE`。M4-T4 不构造最终 `Joint`。

### `Plate`

一张可独立拼装/熨烫的板件。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | str | 稳定 ID，如 `P01` |
| `kind` | enum | `ring \| perimeter \| cross_skeleton \| pin_patch \| cap \| splice` |
| `cells` | `frozenset[(u,v)]` | 实体格 |
| `color_by_cell` | `dict[(u,v), color_id]` | 格色 |
| `holes` | `frozenset[(u,v)]` | 挖空格，不能与 cells 相交 |
| `label` | str | 图纸显示名 |

不变量：非空；颜色键是 cells 子集；holes 与 cells 不相交；必须 4-连通。

### `Joint`

一对互补舌槽。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | str | 稳定 ID，如 `J01` |
| `plate_a/plate_b` | str | 舌件/槽件 |
| `edge_a/edge_b` | str | 接触边 |
| `direction` | enum | `x+ \| x- \| y+ \| y- \| z+ \| z-` |
| `position` | int | 沿边位置 |
| `width/length` | int | 舌宽/舌长，单位格 |
| `joint_type` | enum | `load_bearing \| pin` |
| `tongue_cells` | `frozenset[(x,y,z)]` | 舌实体格 |
| `slot_cells` | `frozenset[(x,y,z)]` | 槽留空格 |

不变量：两板不同；宽长正；舌是槽的子集；槽至少多 1 格余量。所有板件统一采用双面有孔烫法，`Joint` 不携带轻烫区/重烫区字段。

M4-T2 只生成 `JointBoolean` 的舌/槽/余量格，M4-T3 只验证槽口可达性；最终 `Joint` 不区分轻烫区/重烫区，统一由 `RouteFeature.DOUBLE_SIDED_HOLE` 约束，因此不在本任务构造。

### `AssemblyGraph`

板件装配 DAG。

- 节点：板件 ID。
- 边 `p -> q`：`p` 必须先于 `q` 安装。
- 必须无环。
- 必须有唯一汇点（最后封顶件）。
- 封顶方向应为 `z-`（从上往下压合）。

### `Design`

一次完整设计输出。

| 字段 | 说明 |
| --- | --- |
| `project_id` | 项目 ID |
| `bead_spec` | 豆规格 |
| `voxel_grid` | 体素结果 |
| `plates` | 板件 |
| `joints` | 接头 |
| `assembly` | 装配 DAG |
| `route_features` | 路线特征集合 |
| `palette` | 色号 -> 十六进制 |
| `bottom_ring_id` | 底环 ID |

## 4. 路线特征

必需：

- `shape_partitioned`
- `double_sided_hole`
- `glue_free_interlock`

禁止：

- `horizontal_solid_slices`
- `glue`
- `connector_rod`
- `acrylic_rod`
- `true_curved_surface`

## 5. 校验问题

`ValidationIssue` 包含：

- `code`：稳定错误码，如 `PLATE_DISCONNECTED`
- `severity`：`error \| warning`
- `message`：面向用户的中文说明
- `plate_id` / `joint_id`：可选定位

`ValidationReport.ok` 仅当没有 error 时为真。

## 6. 稳定 ID 规则

- 项目：`prj_<12 hex>`
- 作业：`job_<12 hex>`
- 板件：`P01`、`P02`……按装配顺序和空间位置排序
- 接头：`J01`、`J02`……按板件 ID 和位置排序
- 产物：`art_<kind>_<12 hex>`

ID 一旦生成，重跑同一输入应保持稳定；随机 ID 只用于新建实体。
