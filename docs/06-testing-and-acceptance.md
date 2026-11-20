# 测试与物理验收

## 1. 测试金字塔

### 领域单元测试（M1 起）

- 路线守卫：必需特征、禁止特征、异常。
- 舌槽：互补、余量、槽口可达性；所有板件统一双面有孔烫法，不区分轻烫/重烫，标记与孔保留校验由 M4-T5 覆盖。
- 装配 DAG：拓扑排序、环检测、唯一汇点。
- 板件：4-连通、边界、色号。
- 校验器：错误聚合、严重级别。

### 契约测试（M1 起）

- 创建项目 -> 上传图片 -> 编译 -> 查询作业 -> 下载产物。
- 错误码与 HTTP 状态。
- 上传大小/类型/数量限制。
- `apps/api/tests/test_api_contract.py` 和 `test_project_service.py` 已执行；当前 240 项后端测试全部通过，无跳过。

### 黄金样例（M2 起）

- 固定输入模型 -> 固定 VoxelGrid。
- 固定 VoxelGrid -> 固定板件/接头/布局。
- 固定设计 -> 固定 SVG/PDF 哈希（允许字体版本差异时改为结构断言）。
- M2-T1/T2 已加入 `fixtures/m2-normalization.json`：Y-up 盒体 GLB -> `3×9×6` 网格、固定变换矩阵、134 个表面体素、28 个内部体素和 162 个实心体素。
- M2-T3 使用 2×2 纹理平面作为颜色采样回归：4 个表面体素分别匹配 `blue/red/yellow/green` 各 1 颗；同一实心盒体用单色验证 162 个内部体素传播；缺少 UV、无效 UV 和缺少贴图均返回稳定错误码。
- M2-T4 使用同一 Y-up 盒体固定 `z=3` 切片：`3×9` 网格、27 个 `charcoal` 实心格、`#3b3b3b` 色号；同时覆盖默认中间切片、越界 `VOXEL_SLICE_OUT_OF_RANGE` 和缺少 GLB 的 `MODEL_ARTIFACT_NOT_FOUND`。
- M2-T5 使用 `fixtures/m2-voxel-artifact.json` 固定 `voxel_npz` 的缓存键、artifact ID、`3×9×6` 网格、162 个实心体素、`charcoal` 色号和占用/颜色摘要；覆盖 NPZ 往返、缓存参数敏感性、缓存命中不重算、体素化失败重试不调用 Tripo，以及 256³ 性能预算。
- M3-T1 使用 `apps/api/tests/test_layers.py` 固定水平层提取：保留空 z 层、4 邻域分量、对角不连通、环形内孔边界、稳定分量 ID、单位边界边、分量尺寸/面积/色号统计和越界层索引。
- M3-T2 使用 `apps/api/tests/test_contours.py` 固定闭合轮廓：单格、矩形共线简化、L 形凹角、环形内孔、多孔稳定排序、多分量 ID、空层、退化/无效顶点和闭合序列；外轮廓面积减内孔面积与体素面积一致。
- M3-T3 使用 `apps/api/tests/test_bands.py` 固定层带检测：均匀层叠、颜色/面积/孔数/分量数突变、空层单独成带、全空网格、阈值严格大于语义、未着色格、稳定 ID、输入一致性和稳定错误码；共 12 项。
- M3-T4 使用 `apps/api/tests/test_horizontal_plates.py` 固定水平环片：3×3 环形孔、无孔分量跳过、多孔、多分量/多带稳定 ID、空层/空带、网格与分量不一致、孔洞越界/重叠/贴边、轮廓不匹配和记录不变量；共 20 项。无孔分量不会生成水平实心片。
- M3-T5 使用 `apps/api/tests/test_vertical_plates.py` 固定垂直围板：5×3 矩形、3×3 环形孔只取外轮廓、L 形 6 段、十字形截断为 8 段、多层带高度、多带/空带、多分量、列色传播、接头预留区、`start_plate_index`、网格/分量/轮廓/记录不变量和稳定错误码；共 28 项。所有围板均为 `PERIMETER` 矩形直片，无真曲面和水平实心切片。
- M3-T6 使用 `apps/api/tests/test_plate_adjacency.py` 固定板件邻接图：3×3 环形孔生成 4 条环片/围板接触和 4 条垂直段接缝；多层带生成水平叠层；颜色突变切带后生成跨层带垂直堆叠；L 形 6 段围板形成闭合接触环；空设计生成空图；并覆盖稳定 `E01` 编号、法向/位置/接触长度、图查询、规范排序、重复 ID、未知轮廓和稳定错误码；共 12 项。M3-T6 只生成接触候选，不创建舌槽实体格。
- M3-T7 使用 `apps/api/tests/test_cross_skeletons.py` 和 `test_m3_decomposition_golden.py` 固定分解黄金样例：5×5×3 空心方管生成 1 个层带、3 张 `RING` 环片、4 张 `PERIMETER` 围板、3 张 `CROSS_SKELETON` 十字骨架和 20 条稳定接触边；十字骨架取环片最大 4-连通孔，居中生成加号形空白件，并记录源孔格、骨架格、余量格和孔轮廓 ID。孔太小或形状不匹配时分别记录 `HOLE_TOO_SMALL` / `HOLE_SHAPE_UNSUPPORTED`，不会静默生成实心片。黄金样例还固定 `P01..P10` 编号、`E01..E20` 接触边、两组连通分量、所有板件 4-连通、路线守卫和 `DesignValidator` 通过；十字骨架 12 项 + 黄金样例 5 项。
- M4-T1 使用 `apps/api/tests/test_joint_candidates.py` 固定接头候选生成：5×5×3 空心方管从 20 条接触边生成 16 个候选（`J01..J16`）和 4 个 `CONTACT_TOO_SHORT` 跳过（`E15..E18` 垂直段接缝）；12 个环片/围板承力候选为 2 格宽、3 格长、居中位置 1、槽 3×4，2 个水平叠层和 2 个十字堆叠为 1×1 销钉、槽 2×2。11×11×3 厚壁环（壁厚 4 格）生成 4 个 2×3 承力候选，居中位置 4、槽 3×4。测试还覆盖配置校验、记录校验、未知/重复边、边元数据不匹配、空图、短销钉、未处理边和按板查询；共 16 项。M4-T1 只生成描述符，不创建舌槽实体格。
- M4-T2 使用 `apps/api/tests/test_joint_booleans.py` 固定舌槽布尔：5×5×3 和 7×7×3 空心环的候选全部记录 `WALL_TOO_THIN`；11×11×1 厚壁环生成 4 个完整承力布尔；11×11×3 厚壁环生成 12 个完整布尔并跳过 `J01`、`J06`、`J15`、`J16` 四个薄壁候选。`J01` 黄金结果固定 6 个舌实体格、3×4 槽格、6 个余量格、6 个舌根格和 3 个槽口格；测试还覆盖配置/记录校验、重复候选、未知候选/板件、按边/板查询和空提取；共 20 项。M4-T2 不构造最终 `Joint`；所有板件统一采用双面有孔烫法，不区分轻烫区/重烫区。
- M4-T3 使用 `apps/api/tests/test_joint_reachability.py` 固定槽口可达性：11×11×1 厚壁环的 4 个布尔全部可达，`J01` 固定为所需宽度 2、路径宽度 3、槽口 3 格；11×11×3 厚壁环的 12 个布尔全部可达，垂直贯穿槽 `J07`/`J11` 分别位于 `z=1`/`z=2` 的槽腔平面。配置宽度 4 时 4 个布尔全部记录 `SLOT_OPENING_TOO_NARROW`，最大路径宽度 3；封闭孔记录 `NO_FREE_PATH_TO_PLATE_BOUNDARY`，非边界槽口记录 `SLOT_OPENING_NOT_ON_PLATE_BOUNDARY`。测试还覆盖配置/记录校验、按边/板查询、未处理布尔、重复/未知布尔和元数据不匹配；共 19 项。M4-T3 不构造最终 `Joint`；同边间距与防撕裂属于 M4-T4。

### 属性测试（M3 起）

- 任意互补舌槽：舌 ⊆ 槽，余量 ≥ 1。
- 任意装配 DAG：拓扑序覆盖全部节点或检测到环。
- 任意板件切分：每片 4-连通且不超 Bmax。

### 视觉回归（M6 起）

- 展开图、爆炸图、三视图截图对比。
- PDF 逐页渲染对比。

## 2. 路线守卫测试

必须覆盖：

- 必需三特征齐全 -> 通过。
- 出现 `glue` -> 拒绝。
- 出现 `horizontal_solid_slices` -> 拒绝。
- 出现 `connector_rod` / `acrylic_rod` -> 拒绝。
- 缺少 `double_sided_hole` -> 拒绝。
- 异常消息包含缺失/禁止特征。

## 3. 物理验收

### 3.1 打印比例

- 打印 1:1 校验尺。
- 5mm 豆：10 格 = 50mm（允许 ±0.2mm）。
- 2.6mm 豆：10 格 = 26mm（允许 ±0.2mm）。

### 3.2 双面有孔

- 正反两面轻融。
- 每颗豆中心孔完整保留。
- 板件边缘粘合，孔不塌。
- 不出现整片死平塑料。

### 3.3 免胶拼插

- 按 DAG 顺序组装。
- 不需要胶水、连接棒、亚克力杆。
- 插舌能进入槽口，不强行扩孔。
- 组装后环片压围板、围板撑环片。
- 中心十字抗扭。
- 最后封顶件从上往下压合。

### 3.4 稳定性

- 成品站立/放置稳定。
- 重心投影在底环内。
- 轻拿轻放不散。
- 不满足时输出明确失败原因，不静默降级。

## 4. 性能目标

初始目标（单 worker）：

| 操作 | 目标 |
| --- | --- |
| 256³ 体素化 | < 30s |
| 100 板分件 | < 60s |
| 2D 排版 | < 10s |
| SVG 渲染 | < 10s |
| PDF 导出 | < 30s |
| 作业状态轮询 | < 2s 延迟 |

当前开发机基准（5mm 豆、256³ 盒体，仅归一化/表面/实心填充）：`normalize_seconds = 0.005`、`surface_seconds = 1.983`、`solid_seconds = 17.837`、`total_seconds = 19.825`，满足 30s 预算。完整颜色采样尚未纳入该基准；128³ 完整着色体素化约 86s，颜色传播与色卡匹配优化归入 M7-T4。

## 5. 本地命令

```powershell
$env:PYTHONPATH = "apps/api"
.\.venv\Scripts\python.exe -m unittest discover -s apps/api/tests -v
.\.venv\Scripts\python.exe -m compileall -q apps/api/app apps/api/tests scripts
.\.venv\Scripts\ruff.exe check apps/api/app apps/api/tests scripts
$env:MYPYPATH = "apps/api"
.\.venv\Scripts\mypy.exe apps/api/app scripts
.\.venv\Scripts\python.exe scripts\benchmark_voxelization.py --grid-size 256 --max-seconds 30

cd apps\web
pnpm run build
```

当前环境最近一次结果：`Ran 240 tests ... OK`（无跳过）；`compileall: OK`；`ruff: All checks passed!`；`mypy: Success: no issues found in 53 source files`；`pnpm run build: OK`（41 modules）。前端目前没有测试文件，`vitest run` 会以“未发现测试文件”退出。真实 Tripo 账号和 Docker 镜像构建尚未验证。

## 6. 发布门禁

- 领域测试全绿。
- 路线守卫测试全绿。
- 黄金样例结构一致。
- 物理验收清单由至少一次真实打印/熨烫确认。
- 文档与实现一致。
