# PinDou Studio（拼豆工坊）

把同一物体的多视角图片转换为可实际制作的 3D 拼豆图纸。系统通过 Tripo 重建 GLB，再逐步实现实心体素化、按造型分件、双面有孔、免胶拼插、2D 排版和可打印 PDF。

> 当前仓库完成 **M1：项目接入与 Tripo GLB 轮询**、**M2-T1/T2/T3/T4/T5：表面体素化、实心填充、纹理采样、色卡匹配、真实切片预览、体素产物缓存与作业阶段接入**、**M3-T1/T2/T3/T4/T5/T6/T7：水平层、闭合轮廓、层带检测、水平环片、垂直围板、板件邻接图与分解黄金样例**，以及 **M4-T1/T2/T3：接头候选生成、舌槽布尔提取与槽口可达性 BFS**。自锁和出图尚未实现；所有板件统一采用双面有孔烫法，不再区分轻烫区/重烫区。

## 唯一路线

**按造型分件 + 双面有孔 + 免胶拼插。**

以下退化路线被代码和验收规则明确禁止：

- 水平实心切片 + 胶水粘接
- 连接棒、亚克力杆或金属杆贯穿
- 用真曲面代替拼豆的阶梯/折线像素风
- 未经验证的“局部点胶”静默兜底

路线守卫位于 `apps/api/app/domain/route.py`，任何设计输出都必须通过它。

## 单人自用基线

- 不做登录、多用户、权限、配额和分享链接。
- 本地 Windows / macOS 运行，同时保持 Docker 兼容。
- Tripo 使用 **GLB + 轮询**；API Key 只放在服务端环境变量。
- 默认 5mm 标准豆 29×29 板；2.6mm 迷你豆 57×57 板。
- 默认 Perler Standard 色卡，`ΔE = 6.0`。
- 默认 A4 1:1 中文 PDF。
- 局部点胶必须显式确认并生成风险说明，不能静默降级。

## 产品流程

1. 上传同一物体的 3–12 张多视角图片。
2. 调用 Tripo 模型 API 重建 3D 模型，下载 GLB。
3. 以单颗拼豆的物理体积进行实心体素化。
4. 按层带、外轮廓和内部孔洞拆成环片、围板、十字骨架、销钉贴片与封顶件。
5. 为相邻板件生成互补舌槽，校验可达性、间距、双面有孔烫法和装配 DAG。
6. 将板件展开到 2D 拼板网格，输出色号、颗数、坐标框和孔槽标记。
7. 生成爆炸装配图、三视图、装配说明和可打印 PDF。

## 仓库结构

```text
apps/
  api/                 FastAPI 后端、领域模型、SQLite 仓储、Tripo 适配器
  web/                 React + TypeScript + Vite 工作台
docs/
  00-product-brief.md  产品需求基线
  01-architecture.md   系统架构与边界
  02-domain-model.md   领域模型与不变量
  03-algorithm-spec.md 体素化、分件、卡扣、排版算法规范
  04-api-contract.md   API 契约
  05-implementation-plan.md 分阶段任务清单
  06-testing-and-acceptance.md 测试与物理验收
  07-decisions.md      架构决策记录
  08-open-questions.md 已确认事项与剩余风险
  09-glossary.md       术语表
  10-codex-task-template.md 任务模板
  11-environment.md    本地环境与限制
  12-requirements-traceability.md 需求追踪矩阵
fixtures/              黄金样例与演示数据
scripts/               本地开发脚本
```

## 本地启动

### macOS / Linux（推荐）

前置条件：Python 3.12+、Node.js 20+、pnpm。

```bash
cd /path/to/perler-beads-hama-beads-fuse-beads
chmod +x scripts/dev.sh scripts/test.sh
./scripts/dev.sh
```

首次运行会自动创建 `.venv`、安装后端依赖、复制 `.env`、安装前端依赖，并同时启动 API 和 Vite。按 `Ctrl+C` 停止。

如果希望分开启动：

```bash
# 终端 1：后端
cd /path/to/perler-beads-hama-beads-fuse-beads
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e "apps/api[dev]"
cp .env.example .env
# 编辑 .env，填入 TRIPO_API_KEY
python -m uvicorn app.main:app --app-dir apps/api --reload
```

```bash
# 终端 2：前端
cd /path/to/perler-beads-hama-beads-fuse-beads/apps/web
pnpm install
pnpm run dev
```

打开 `http://localhost:5173`，API 文档在 `http://127.0.0.1:8000/docs`。

macOS 12.1（Monterey）说明：项目没有 Windows 专属运行时依赖，可以原生运行；建议使用 python.org 的 Python 3.12+ 和 Node.js 20/22 官方安装包。Apple Silicon 选择 arm64，Intel 选择 x64。Tripo 重建在云端，Mac 本地不需要 CUDA/GPU；macOS 12.1 上不建议依赖最新版 Docker Desktop，优先使用上面的原生启动方式。如果硬件支持，建议升级到 macOS 12.7.6 或更高版本。

### Windows（PowerShell）

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e "apps/api[dev]"
Copy-Item .env.example .env
# 编辑 .env，填入 TRIPO_API_KEY
uvicorn app.main:app --app-dir apps/api --reload
```

打开 `http://127.0.0.1:8000/docs` 查看 OpenAPI。

另开终端启动前端：

```powershell
cd apps/web
pnpm install
pnpm run dev
```

打开 `http://localhost:5173`。Vite 会把 `/api` 代理到 `http://127.0.0.1:8000`。

### Docker Compose

```bash
cp .env.example .env
# 编辑 .env，填入 TRIPO_API_KEY
docker compose up --build
```

Windows PowerShell 使用 `Copy-Item .env.example .env` 代替 `cp`。

打开 `http://localhost:5173`。API 数据持久化在 Compose volume `pindou-data`，容器内路径为 `/data`。

## API 概览

- `GET /health`
- `POST /api/v1/projects`
- `GET /api/v1/projects/{project_id}`
- `POST /api/v1/projects/{project_id}/images`
- `POST /api/v1/projects/{project_id}/compile`
- `GET /api/v1/jobs/{job_id}`
- `POST /api/v1/jobs/{job_id}/retry`
- `GET /api/v1/projects/{project_id}/artifacts`
- `GET /api/v1/projects/{project_id}/artifacts/{artifact_id}`
- `GET /api/v1/projects/{project_id}/voxel-preview`

完整字段、错误码和状态机见 `docs/04-api-contract.md`。

## 当前状态

- [x] 产品需求基线、路线守卫、领域模型、API 契约和任务拆分
- [x] 图片上传校验：JPG / PNG / WebP 魔数、数量、大小、重复检测、文件名清洗
- [x] 本地对象存储：原图、模型、产物目录隔离与路径逃逸防护
- [x] Tripo 客户端：上传图片、创建多视角任务、轮询、下载 GLB
- [x] SQLite 持久化：项目、图片、作业、阶段、产物
- [x] 前端真实上传向导、作业轮询、失败重试和 GLB 产物下载
- [x] 领域测试、存储测试和契约测试（258 项全部通过，无跳过）
- [x] 后端依赖、前端依赖、类型检查和生产构建验证
- [x] M2-T1 GLB 归一化：Y-up→Z-up、毫米缩放、网格对齐、表面体素化黄金样例
- [x] M2-T2 实心体素化：外部泛洪内部填充、闭合网格校验、确定性黄金样例
- [x] M2-T3 纹理采样与色卡匹配：最近三角面 UV、CIEDE2000、内部颜色传播、稳定错误码
- [x] M2-T4 体素预览：真实 GLB 切片、切片导航、色号图例、采样参数和可操作空状态
- [x] M2-T5 体素产物：`voxel_npz` 持久化、确定性缓存、作业 `voxelize` 阶段、失败重试不重复调用 Tripo、256³ 性能基准
- [x] M3-T1 水平层提取：保留空 z 层、4-连通分量、稳定 ID、边界格与顺时针单位边界边
- [x] M3-T2 外轮廓追踪：右手规则闭合轮廓、外轮廓/内孔分类、孔洞包含校验、整数格共线简化
- [x] M3-T3 层带检测：颜色直方图距离、外轮廓面积/等效半径、孔数/分量数变化、空层切分与稳定层带 ID
- [x] M3-T4 水平环片：按层带和 4-连通分量生成外轮廓减内孔的 `RING` 板件，无孔分量显式跳过，稳定 `P01` 编号
- [x] M3-T5 垂直围板：按外轮廓直边生成 4–8 段 `(u,v)` 矩形 `PERIMETER` 直片，保留层带高度、格色、接头预留区和稳定编号
- [x] M3-T6 板件邻接图：从层带、轮廓和板件局部网格生成确定性无向接触图，记录接触类型、法向、位置、接触长度和来源元数据
- [x] M3-T7 分解黄金样例：用 5×5×3 空心方管固定 10 张板件（3 环片 + 4 围板 + 3 十字骨架）、20 条接触边、稳定连通分量、路线守卫和 `DesignValidator` 结果
- [x] M4-T1 接头候选生成：按接触边稳定生成 `J01`、`J02`…… 候选，记录边、方向、居中位置、舌宽/舌长、槽余量、接头类型和接触长度；过短接触边显式记录 `CONTACT_TOO_SHORT` 跳过
- [x] M4-T2 舌槽布尔：把候选转成 1 格厚舌实体与槽留空格，校验舌 ⊆ 槽、至少 1 格余量、槽口开在板边界、舌根承力深度和两板实体不相交；薄壁候选稳定记录 `WALL_TOO_THIN`，不静默缩小接头
- [x] M4-T3 槽口可达性：在接触框架的槽腔平面 `u-v` 内固定 `w` 做全空格 BFS，要求从槽口到达扩展后的板外边界，路径宽度至少为 `max(配置值, 舌宽)`；11×11×1 厚壁环 4 个布尔全部可达，11×11×3 厚壁环 12 个布尔全部可达，窄口/封闭孔/非边界槽口稳定跳过
- [x] M4-T4 同边间距与防撕裂：同时检查 A 侧舌位和 B 侧槽位，要求起点间距至少为 `max(相邻舌宽) + 2`，槽体不得相接或重叠，并保留至少 2 格边缘余量；过近/连续开槽/边缘不足记录稳定跳过原因
- [ ] 真实 Tripo 账号联调与 GLB 可读性验证
- [ ] M4-T5+ 双面有孔烫法标记、自锁与装配 DAG 校验
- [ ] 2D 排版、爆炸图、PDF 导出

## 验证命令

### macOS / Linux

```bash
cd /path/to/perler-beads-hama-beads-fuse-beads
chmod +x scripts/test.sh
./scripts/test.sh

cd apps/web
pnpm run build
```

`scripts/test.sh` 会依次运行后端单元测试、`compileall`、`ruff` 和 `mypy`。

### Windows（PowerShell）

```powershell
$env:PYTHONPATH = "apps/api"
.\.venv\Scripts\python.exe -m unittest discover -s apps/api/tests -v
.\.venv\Scripts\python.exe -m compileall -q apps/api/app apps/api/tests scripts
.\.venv\Scripts\ruff.exe check apps/api/app apps/api/tests scripts
$env:MYPYPATH = "apps/api"
.\.venv\Scripts\mypy.exe apps/api/app scripts

cd apps\web
pnpm run build
```

当前依赖已安装并验证：后端 258 项测试通过，`ruff` 与 `mypy`（54 个源文件）通过，前端 `tsc --noEmit` 与 `vite build` 通过。真实 Tripo 账号联调和 Docker 镜像构建仍未验证。详见 `docs/11-environment.md`。

### GLB 归一化调试

```powershell
$env:PYTHONPATH = "apps/api"
.\.venv\Scripts\python.exe scripts\normalize_glb.py path\to\model.glb --target-height-mm 80 --bead-size 5mm --source-up-axis y
```

输出包含归一化后的网格尺寸、毫米边界、4×4 变换矩阵、表面体素数、内部体素数和实心体素数。该命令同时执行 M2-T1 表面体素化和 M2-T2 实心填充。

### 颜色采样调试

```powershell
$env:PYTHONPATH = "apps/api"
.\.venv\Scripts\python.exe scripts\colorize_glb.py path\to\model.glb --target-height-mm 80 --bead-size 5mm --delta-e-tolerance 6.0
```

输出包含网格尺寸、实心体素数、每色颗数和实际使用的色卡。内置 Perler Standard 是 32 色近似基线，不是官方完整色卡；项目级色卡覆盖将在后续任务接入。

## 下一步

下一步从 **M4-T5** 开始：在 M4-T4 已通过同板同边间距和防撕裂校验的接头上，生成双面有孔烫法标记与孔保留校验。所有板件统一采用双面有孔烫法，不区分轻烫区/重烫区；M4-T4 只做间距和边缘余量校验，不构造最终 `Joint`。后续必须继续保证内部不填实，不得回退到水平实心切片或真曲面。

## 关键文档

- 产品边界：`docs/00-product-brief.md`
- 架构与模块职责：`docs/01-architecture.md`
- 算法规则：`docs/03-algorithm-spec.md`
- API 契约：`docs/04-api-contract.md`
- 下一步任务：`docs/05-implementation-plan.md`
- 物理验收：`docs/06-testing-and-acceptance.md`
- 需求追踪矩阵：`docs/12-requirements-traceability.md`
