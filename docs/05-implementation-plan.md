# 实施计划

按依赖顺序推进。每个任务完成后勾选，并在 PR/提交说明中写任务 ID。

需求来源与验收映射见 `docs/12-requirements-traceability.md`；后续任务提示词应引用对应需求 ID。

## M0 项目框架（已完成）

- [x] M0-T1 建立单仓结构、README、AGENTS 和文档基线
- [x] M0-T2 定义领域模型：BeadSpec、VoxelGrid、Plate、Joint、AssemblyGraph、Design
- [x] M0-T3 实现路线守卫 RouteGuard
- [x] M0-T4 实现基础 DesignValidator（连通性、板限、舌槽、DAG、色卡）
- [x] M0-T5 建立 FastAPI 路由骨架（M1 已替换为 SQLite 持久化）
- [x] M0-T6 建立 React 工作台壳层与演示数据
- [x] M0-T7 建立领域单元测试

验收：`python -m unittest discover -s apps/api/tests -v` 通过；`python -m compileall apps/api/app` 通过。

## M1 项目接入与 Tripo（已完成）

- [x] M1-T1 图片上传校验：MIME/魔数、数量、大小、视角去重
- [x] M1-T2 本地对象存储：项目目录、原图、模型、产物隔离
- [x] M1-T3 Tripo 客户端：提交多视角任务、轮询、下载 GLB
- [x] M1-T4 作业持久化：SQLite 表、状态机、失败重试
- [x] M1-T5 前端上传向导与作业进度
- [x] M1-T6 契约测试：上传 -> 重建 -> 作业成功（依赖缺失时自动跳过）

验收：上传 3–12 张图片，Tripo 返回模型，作业状态可轮询，失败可重试。真实 Tripo 账号联调仍待 API Key 验证。

## M2 实心体素化（已完成）

- [x] M2-T1 网格归一化与坐标变换（GLB 加载、Y-up→Z-up、毫米缩放、网格对齐、表面体素化）
- [x] M2-T2 实心体素化（外部泛洪填充、闭合网格校验）
- [x] M2-T3 纹理采样与色卡匹配（最近三角面 UV 采样、CIEDE2000、内部颜色传播）
- [x] M2-T4 体素预览（真实 GLB 切片、切片导航、色号图例、采样参数）
- [x] M2-T5 体素化黄金样例、性能测试与作业阶段接入

验收：样例模型生成确定性 VoxelGrid；内部实心；颜色颗数可复现。M2-T1 已用 `fixtures/m2-normalization.json` 固定 `3×9×6` 网格、变换矩阵和 134 个表面体素；M2-T2 已通过外部泛洪填充得到 162 个实心体素（内部 28 个），非闭合网格返回 `NORMALIZATION_NOT_WATERTIGHT`；M2-T3 已用 2×2 纹理平面固定 `blue/red/yellow/green` 各 1 颗，并用单色盒体验证 162 个内部体素的表面色传播；M2-T4 已用同一盒体固定 `z=3` 切片的 27 个 `charcoal` 格和 `#3b3b3b` 色号，前端可逐层查看且无项目时显示真实空状态；M2-T5 已把 `voxelize` 接入作业流水线，将结果持久化为 `voxel_npz`，固定缓存键和 artifact ID，预览切片复用缓存，体素化失败重试不重复调用 Tripo，并补充 256³ 性能基准（19.825s，满足 30s 预算）。

## M3 层带与板件分解（当前）

- [x] M3-T1 水平层提取与 4-连通边界
- [x] M3-T2 外轮廓追踪与折线简化
- [x] M3-T3 层带检测
- [x] M3-T4 水平环片（外轮廓 − 内孔）
- [x] M3-T5 垂直围板（N=4–8 段直片）
- [x] M3-T6 板件邻接图
- [x] M3-T7 分解黄金样例

验收：演示物体输出环片 + 围板 + 十字骨架；无真曲面；板件 4-连通。M3-T1 已实现 `Layer`/`LayerComponent`/`BoundaryEdge`，保留所有 z 层（含空层），按 4 邻域分解连通分量，并输出顺时针单位边界边；8 项领域测试覆盖对角不连通、环形内孔、空层、稳定 ID 和边界几何。M3-T2 已实现右手规则闭合轮廓追踪、外轮廓/内孔分类、孔洞包含校验和整数格共线简化；9 项测试覆盖单格、矩形、L 形凹角、环形孔、多孔、多分量、空层、退化轮廓和稳定 ID。M3-T3 已实现 `LayerBandConfig`、`LayerBandMetrics`、`BandTransition`、`LayerBand` 和 `LayerBandExtraction`，按颜色直方图距离、外轮廓面积/等效半径、孔数/分量数变化切分稳定层带，空层单独成带；12 项测试覆盖均匀层叠、颜色/面积/孔数/分量突变、空层、阈值严格大于语义、输入一致性和稳定错误码。M3-T4 已实现 `HorizontalPlate`、`SkippedHorizontalComponent` 和 `HorizontalPlateExtraction`，用扫描线把外轮廓与内孔栅格化，生成 `PlateKind.RING` 板件并校验外轮廓减内孔等于分量实体格；无孔分量记录 `NO_INNER_HOLE` 跳过，稳定生成 `P01`、`P02`……；20 项测试覆盖环形、多孔、多分量/多带、空层、网格/分量不一致、孔洞越界/重叠/贴边、轮廓不匹配和记录不变量。M3-T5 已实现 `VerticalPlateConfig`、`VerticalPlate` 和 `VerticalPlateExtraction`，把外轮廓轴对齐直边按累计边长合并为 4–8 段，生成 `PlateKind.PERIMETER` 矩形直片；高度取层带层数，颜色按每列内侧实体格传播，段两端记录 `joint_margin_cells` 预留区，稳定生成 `P01`、`P02`……并支持 `start_plate_index` 偏移；28 项测试覆盖矩形/环形孔/L 形/十字形、多层带、多带、空带、多分量、颜色、预留区、编号、网格/分量/轮廓/记录不变量和稳定错误码。M3-T6 已实现 `PlateContactKind`、`PlateContactEdge`、`PlateContactGraph` 和 `PlateAdjacencyExtraction`，从水平环片、垂直围板、层带和轮廓生成确定性无向接触图；覆盖环片/围板接触、垂直段接缝、水平叠层和跨层带垂直堆叠，记录法向、位置、接触长度和来源元数据，稳定生成 `E01`、`E02`……；12 项测试覆盖环形、L 形、多层带、相邻层带、空设计、稳定排序、图查询和稳定错误码。M3-T7 已实现 `CrossSkeletonConfig`、`CrossSkeleton`、`SkippedCrossSkeleton`、`CrossSkeletonExtraction`、`DecompositionConfig`、`DecompositionExtraction` 和 `decompose_voxel_grid`，从每个水平环片的最大 4-连通孔生成居中的加号形 `PlateKind.CROSS_SKELETON` 空白件，记录源孔格、骨架格、余量格和孔轮廓 ID；孔太小或形状不匹配时记录 `HOLE_TOO_SMALL` / `HOLE_SHAPE_UNSUPPORTED`，绝不静默生成实心片。`fixtures/m3-decomposition.json` 固定 5×5×3 空心方管的 48 个体素、1 个层带、3 张环片、4 张围板、3 张十字骨架、20 条接触边、稳定连通分量和 `DesignValidator` 结果；5 项黄金测试 + 12 项十字骨架测试覆盖孔选择、跳过原因、编号、记录不变量、接触图、4-连通、路线守卫和校验器。

## M4 卡扣合成与自锁

- [x] M4-T1 接头候选生成（边、方向、位置、宽长）
- [x] M4-T2 舌槽布尔与 1 格余量
- [x] M4-T3 槽口可达性 BFS
- [x] M4-T4 同边间距与防撕裂
- [ ] M4-T5 双面有孔烫法标记与孔保留校验
- [ ] M4-T6 装配 DAG 与拓扑排序
- [ ] M4-T7 无胶自锁四判据
- [ ] M4-T8 失败回退与显式局部点胶标注
- [ ] M4-T9 接头属性测试

验收：所有接头互补、可达、无孤儿；DAG 无环且唯一汇点；免胶判据全满足。M4-T1 已实现 `JointCandidateConfig`、`JointCandidate`、`SkippedJointCandidate`、`JointCandidateExtraction` 和 `generate_joint_candidates`：按接触边顺序稳定生成 `J01`、`J02`…… 候选，记录接触边、规范板件、接触类型、法向、居中起始位置、舌宽/舌长、槽余量、接头类型和接触长度；Z 法向堆叠面生成 1×1 销钉候选，其余接触按 `JointType` 选择承力或销钉尺寸。接触边扣除两端余量后放不下“舌宽 + 槽余量”时记录 `CONTACT_TOO_SHORT`，不静默降级。5×5×3 空心方管黄金样例生成 16 个候选（12 个环片/围板承力候选 + 2 个水平叠层销钉 + 2 个十字堆叠销钉）和 4 个过短的垂直段接缝跳过；11×11×3 厚壁环（壁厚 4 格）生成 4 个 2×3 承力候选。16 项领域测试覆盖候选尺寸/居中、稳定编号、厚壁环、配置校验、记录校验、未知/重复边、边元数据不匹配、空图、短销钉、未处理边和按板查询。

M4-T2 已实现 `JointBooleanConfig`、`JointBoolean`、`SkippedJointBoolean`、`JointBooleanExtraction` 和 `generate_joint_booleans`：把候选转成世界坐标的一格厚舌实体格和槽留空格，校验舌 ⊆ 槽、至少 1 格余量、槽口开在接触边界、舌根承力深度、壁厚和两板实体不相交。5×5×3 与 7×7×3 环的候选全部记录 `WALL_TOO_THIN`；11×11×1 厚壁环生成 4 个完整布尔；11×11×3 厚壁环生成 12 个完整布尔并跳过 4 个薄壁候选。20 项领域测试覆盖配置/记录校验、稳定编号、薄壁跳过、厚壁黄金结果、重复候选、未知候选/板件和按边/板查询。所有板件统一采用双面有孔烫法，不区分轻烫区/重烫区；M4-T2 不构造最终 `Joint`，槽口可达性 BFS 留给 M4-T3。

M4-T3 已实现 `JointReachabilityConfig`、`JointReachability`、`SkippedJointReachability`、`JointReachabilityExtraction` 和 `generate_joint_reachability`：在接触框架的槽腔平面 `u-v` 内固定厚度轴 `w`，把板 B 剩余实体投影为障碍，从槽口出发做全空格 BFS，并要求到达扩展后的板外边界。所需路径宽度为 `max(min_path_width_cells, 舌宽)`；只有属于某个 `w×w` 全空格方块的格才可通行，二分搜索得到最大可达宽度。11×11×1 厚壁环的 4 个布尔全部可达，11×11×3 厚壁环的 12 个布尔全部可达；`J01` 固定为 `required_width_cells = 2`、`path_width_cells = 3`、槽口 3 格。配置宽度 4 时记录 `SLOT_OPENING_TOO_NARROW`，封闭孔记录 `NO_FREE_PATH_TO_PLATE_BOUNDARY`，非边界槽口记录 `SLOT_OPENING_NOT_ON_PLATE_BOUNDARY`。19 项领域测试覆盖配置/记录校验、薄厚壁黄金结果、垂直贯穿槽、按边/板查询、未处理布尔和稳定错误码。M4-T3 不构造最终 `Joint`；同边间距与防撕裂属于 M4-T4。

M4-T4 已实现 `JointSpacingConfig`、`JointSpacing`、`SkippedJointSpacing`、`JointSpacingExtraction` 和 `generate_joint_spacing`：同时投影 A 侧舌 footprint 与 B 侧槽 footprint，按 `(plate_id, contact_edge)` 检查同板同边冲突；起点间距至少为 `max(相邻舌宽) + 2`，槽体之间至少保留 1 格，槽 footprint 到接触边两端至少保留 `max(2, edge_margin_cells)`。先出现且满足规则的接头保留，后续冲突记录 `SPACING_TOO_NARROW`、`CONTINUOUS_SLOT` 或 `EDGE_MARGIN_INSUFFICIENT`，不静默缩短、移动或改方向。11×11×1 的 4 个可达接头和 11×11×3 的 12 个可达接头全部通过；18 项领域测试覆盖 A/B 双侧同边、精确间距、间距不足、连续开槽、最大舌宽、边缘余量、配置/记录校验、重复/未知/元数据不匹配和空提取。M4-T4 不构造最终 `Joint`；双面有孔烫法标记与孔保留校验属于 M4-T5。

## M5 2D 排版与 BOM

- [ ] M5-T1 板件局部网格映射
- [ ] M5-T2 颜色量化与 ΔE 合并
- [ ] M5-T3 Bmax 切分与拼接舌
- [ ] M5-T4 大网格平铺（1 格间距）
- [ ] M5-T5 坐标框、编号、孔槽标记
- [ ] M5-T6 色号图例与每色颗数
- [ ] M5-T7 BOM CSV

验收：所有板件进入一张大网格；无重叠；图例颗数与体素一致。

## M6 渲染与 PDF

- [ ] M6-T1 SVG 展开网格图
- [ ] M6-T2 爆炸装配图
- [ ] M6-T3 成品三视图
- [ ] M6-T4 装配步骤文案
- [ ] M6-T5 1:1 打印校验尺
- [ ] M6-T6 中文 PDF 字体嵌入
- [ ] M6-T7 视觉回归测试

验收：A4/A3 PDF 可打印；1:1 校验尺准确；爆炸图顺序与 DAG 一致。

## M7 门禁与工程化

- [ ] M7-T1 完整 DesignValidator 门禁
- [ ] M7-T2 路线守卫回归测试
- [ ] M7-T3 错误码与前端可操作提示
- [ ] M7-T4 性能优化与缓存
- [ ] M7-T5 幂等重跑与中间产物恢复
- [ ] M7-T6 可观测性（日志/指标/追踪）
- [ ] M7-T7 安全审计（上传、下载、密钥）

验收：任一失败都有稳定错误码；重跑不重复调用 Tripo；路线不可绕过。

## M8 生产化（单人自用可跳过）

当前产品只面向单人自用，不做登录、多用户、权限、配额和计费。M8 保留为未来可选生产化路线，不阻塞 M2–M7。

- [ ] M8-T1 PostgreSQL + S3/MinIO
- [ ] M8-T2 队列 worker 与并发控制
- [ ] M8-T3 用户/项目权限
- [ ] M8-T4 配额与计费
- [ ] M8-T5 部署脚本与健康检查
- [ ] M8-T6 备份、保留、删除策略

验收：多用户隔离；作业可恢复；监控告警；部署可回滚。

## 推荐下一步

从 **M4-T5** 开始：在 M4-T4 已通过同板同边间距和防撕裂校验的接头上，生成双面有孔烫法标记与孔保留校验。所有板件统一采用双面有孔烫法，不区分轻烫区/重烫区；M4-T4 只做间距和边缘余量校验，不构造最终 `Joint`。后续继续禁止真曲面、水平实心切片和胶水连接。
