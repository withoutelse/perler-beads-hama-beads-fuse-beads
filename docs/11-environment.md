# 本地环境记录

记录当前开发容器的实际能力，避免后续 Codex 误判“已验证”或“可联网安装”。

## 已确认

- Python：3.12.0
- Node：24.22.3
- pnpm：11.25.0
- 工作区：`C:\Users\ykzhuang\Documents\Codex\2026-11-19\perler-beads-hama-beads-fuse-beads`
- 后端虚拟环境：`.venv`，已安装 `apps/api[dev]` 全部依赖。
- 前端依赖：`apps/web/node_modules` 已安装，`pnpm-lock.yaml` 已生成。
- 后端测试：240 项全部通过，无跳过。
- 后端类型检查：`mypy apps/api/app scripts` 通过（53 个源文件）。
- 后端 lint：`ruff check apps/api/app apps/api/tests scripts` 通过。
- 前端类型检查：`tsc --noEmit` 通过。
- 前端生产构建：`vite build` 通过，产物位于 `apps/web/dist`。

## macOS 12.1（Monterey）兼容性

尚未在真实 Mac 上实测；按当前依赖和脚本判断可以原生运行。项目没有 Windows 专属运行时依赖，Tripo 重建在云端完成。

推荐环境：

- Python 3.12+（python.org 安装包或 pyenv）
- Node.js 20/22 + pnpm
- Apple Silicon 使用 arm64，Intel 使用 x86_64

一键启动：

```bash
cd /path/to/perler-beads-hama-beads-fuse-beads
chmod +x scripts/dev.sh scripts/test.sh
./scripts/dev.sh
```

分开启动：

```bash
cd /path/to/perler-beads-hama-beads-fuse-beads
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e "apps/api[dev]"
cp .env.example .env
# 编辑 .env，填入 TRIPO_API_KEY
python -m uvicorn app.main:app --app-dir apps/api --reload
```

```bash
cd /path/to/perler-beads-hama-beads-fuse-beads/apps/web
pnpm install
pnpm run dev
```

验证：

```bash
cd /path/to/perler-beads-hama-beads-fuse-beads
chmod +x scripts/test.sh
./scripts/test.sh

cd apps/web
pnpm run build
```

注意：

- `scripts/dev.ps1`、`scripts/test.ps1` 和 README 的 PowerShell 命令仅适用于 Windows；macOS 使用 `scripts/dev.sh`、`scripts/test.sh`。
- macOS 12.1 较旧，Homebrew 的新版 formula 可能不兼容；优先使用官方安装包、pyenv 或 nvm。
- 不建议依赖最新版 Docker Desktop；优先使用原生启动方式。
- Tripo 重建在云端，Mac 本地不需要 CUDA/GPU；如果硬件支持，建议升级到 macOS 12.7.6 或更高版本。
- 真实 Tripo 重建仍需 `TRIPO_API_KEY`；没有 Key 只能运行界面、测试和本地领域流程。

## 当前限制

- 没有真实 Tripo API Key，GLB 下载和真实接口字段尚未联调。
- macOS 12.1 兼容性尚未在真实 Mac 上实测；启动脚本已提供，但需在 Mac 上执行一次 `scripts/test.sh` 和 `pnpm run build` 确认。
- 实心体素化、纹理采样、色卡匹配、M2-T4 体素切片预览和 M2-T5 `voxelize` 作业阶段已完成；体素结果持久化为 `voxel_npz`，预览切片复用缓存。
- M3-T1 水平层提取与 4-连通边界已完成：保留空 z 层、稳定分量 ID、边界格和顺时针单位边界边。
- M3-T2 外轮廓追踪与折线简化已完成：右手规则闭合轮廓、外轮廓/内孔分类、孔洞包含校验、稳定多孔排序和整数格共线简化。
- M3-T3 层带检测已完成：颜色直方图距离、外轮廓面积/等效半径、孔数/分量数变化、空层切分、稳定层带 ID 和显式阈值。
- M3-T4 水平环片已完成：按层带和 4-连通分量生成外轮廓减内孔的 `RING` 板件，无孔分量记录 `NO_INNER_HOLE` 跳过，稳定 `P01` 编号；扫描线栅格化、孔洞越界/重叠和轮廓一致性均有稳定错误码。
- M3-T5 垂直围板已完成：外轮廓轴对齐直边按累计边长合并为 4–8 段，生成带层带高度、列色和 `joint_margin_cells` 预留区的 `PERIMETER` 矩形直片；支持多带、多分量、空带跳过和 `start_plate_index` 偏移。
- M3-T6 板件邻接图已完成：从水平环片、垂直围板、层带和轮廓生成确定性无向接触图，覆盖环片/围板接触、垂直段接缝、水平叠层和跨层带垂直堆叠；稳定生成 `E01` 编号并记录法向、位置、接触长度和来源元数据。
- M3-T7 分解黄金样例已完成：`CrossSkeletonConfig`、`CrossSkeleton`、`CrossSkeletonExtraction` 从每个水平环片的最大 4-连通孔生成加号形 `CROSS_SKELETON` 空白件，记录源孔/骨架/余量格和孔轮廓 ID；`DecompositionConfig`、`DecompositionExtraction` 和 `decompose_voxel_grid` 串联 M3-T1–T7。`fixtures/m3-decomposition.json` 固定 5×5×3 空心方管的 48 个体素、10 张板件、20 条接触边、两组连通分量、路线守卫和 `DesignValidator` 结果。
- M4-T1 接头候选生成已完成：`JointCandidateConfig`、`JointCandidate`、`SkippedJointCandidate`、`JointCandidateExtraction` 和 `generate_joint_candidates` 按接触边稳定生成 `J01`、`J02`…… 描述符，记录边、方向、居中位置、舌宽/舌长、槽余量、接头类型和接触长度；Z 法向堆叠面生成 1×1 销钉，其余接触按 `JointType` 选择承力/销钉尺寸，过短接触边记录 `CONTACT_TOO_SHORT`。5×5×3 黄金样例生成 16 个候选和 4 个跳过；M4-T1 不创建舌槽实体格。
- M4-T2 舌槽布尔已完成：`JointBooleanConfig`、`JointBoolean`、`SkippedJointBoolean`、`JointBooleanExtraction` 和 `generate_joint_booleans` 把候选转成世界坐标的一格厚舌实体格和槽留空格，校验舌 ⊆ 槽、至少 1 格余量、槽口开在接触边界、舌根承力深度、壁厚和两板实体不相交。5×5×3 与 7×7×3 环全部记录 `WALL_TOO_THIN`；11×11×1 厚壁环生成 4 个完整布尔；11×11×3 厚壁环生成 12 个完整布尔并跳过 4 个薄壁候选。
- M4-T3 槽口可达性已完成：`JointReachabilityConfig`、`JointReachability`、`SkippedJointReachability`、`JointReachabilityExtraction` 和 `generate_joint_reachability` 在接触框架的槽腔平面 `u-v` 内固定 `w` 做全空格 BFS，要求槽口到达扩展后的板外边界，路径宽度至少为 `max(配置值, 舌宽)`。11×11×1 的 4 个布尔和 11×11×3 的 12 个布尔全部可达；配置宽度 4 时记录 `SLOT_OPENING_TOO_NARROW`，封闭孔记录 `NO_FREE_PATH_TO_PLATE_BOUNDARY`。所有板件统一采用双面有孔烫法，不区分轻烫区/重烫区；M4-T3 不构造最终 `Joint`，同边间距与防撕裂属于 M4-T4。
- M4-T4 同边间距与防撕裂已完成：`JointSpacingConfig`、`JointSpacing`、`SkippedJointSpacing`、`JointSpacingExtraction` 和 `generate_joint_spacing` 同时检查 A 侧舌 footprint 与 B 侧槽 footprint，按 `(plate_id, contact_edge)` 施加 `max(相邻舌宽) + 2` 的起点间距、至少 1 格槽体间隔和至少 2 格边缘余量；过近、连续开槽和边缘不足分别记录稳定原因。11×11×1 的 4 个可达接头和 11×11×3 的 12 个可达接头全部通过，18 项领域测试通过；M4-T4 不构造最终 `Joint`。
- 256³ 归一化 + 表面体素化 + 实心填充基准为 19.825s，满足 30s 预算；该基准不含完整颜色采样。完整 128³ 着色体素化约 86s，颜色传播与色卡匹配优化归入 M7-T4。
- 内置 Perler Standard 为 32 色近似基线，不是官方完整色卡；后续应允许项目级色卡配置覆盖。
- Docker 运行骨架已提供（`docker-compose.yml`、`apps/api/Dockerfile`、`apps/web/Dockerfile`），但当前环境没有 `docker` 命令，未执行镜像构建验证。
- 前端目前没有 `*.test.ts` / `*.spec.ts` 文件，`vitest run` 会以“未发现测试文件”退出；这不代表构建失败。
- `pnpm run build` 在沙箱内可能因 `esbuild` 启动子进程返回 `spawn EPERM` 失败；本次已在沙箱外验证通过。
- 当前网络环境对 PyPI/npm 的 HTTPS 直连不稳定；安装时使用了可访问的 HTTP 镜像和系统代理。不要把镜像地址写死到项目配置中，换网络后应优先恢复官方源。

## 已验证命令（Windows）

```powershell
$env:PYTHONPATH = "apps/api"
.\.venv\Scripts\python.exe -m unittest discover -s apps/api/tests -v
.\.venv\Scripts\python.exe -m compileall -q apps/api/app apps/api/tests scripts
.\.venv\Scripts\ruff.exe check apps/api/app apps/api/tests scripts
$env:MYPYPATH = "apps/api"
.\.venv\Scripts\mypy.exe apps/api/app scripts
.\.venv\Scripts\python.exe scripts\benchmark_voxelization.py --grid-size 256 --max-seconds 30
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000

cd apps\web
pnpm run build

cd ..
$env:PYTHONPATH = "apps/api"
.\.venv\Scripts\python.exe scripts\normalize_glb.py path\to\model.glb --target-height-mm 80
.\.venv\Scripts\python.exe scripts\colorize_glb.py path\to\model.glb --target-height-mm 80 --delta-e-tolerance 6.0
```

最近结果：

- `Ran 240 tests ... OK`（无跳过）
- `compileall: OK`
- `ruff: All checks passed!`
- `mypy: Success: no issues found in 53 source files`
- `benchmark_voxelization: total_seconds=19.825, within_budget=true`
- `GET /health: {"status":"ok","service":"pindou-studio-api","version":"0.1.0"}`
- `pnpm run build: tsc --noEmit + vite build OK`
- `vite build: 41 modules transformed`

如果依赖安装仍失败，先检查 registry、代理和证书，不要通过删除类型检查或放宽测试绕过。

## 真实 Tripo 联调

1. 复制 `.env.example` 为 `.env`。
2. 填入 `TRIPO_API_KEY`。
3. 上传 3–12 张同一物体的多视角图片。
4. 确认 `POST /projects/{id}/compile` 进入 `queued`。
5. 轮询 `GET /jobs/{id}` 到 `succeeded`。
6. 下载 `model_glb` 和 `voxel_npz` 产物，确认 GLB 可被体素化读取且 NPZ 可被 `load_voxel_artifact` 读取。

若真实接口字段与当前假设不同，只调整 `apps/api/app/pipeline/adapters/tripo.py`，不要改变 `RouteGuard` 或领域路线。

## Docker 验证

```powershell
Copy-Item .env.example .env
# 填入 TRIPO_API_KEY
docker compose up --build
```

验收：`http://localhost:5173` 可打开工作台，`http://localhost:8000/health` 返回 `status=ok`，上传与作业数据写入 `pindou-data` volume。
