# PinDou Studio API

FastAPI 后端、纯 Python 领域核心、SQLite 持久化和 Tripo GLB 轮询适配器。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e "apps/api[dev]"
uvicorn app.main:app --app-dir apps/api --reload
```

领域测试不依赖第三方包：

```powershell
$env:PYTHONPATH = "apps/api"
python -m unittest discover -s apps/api/tests -v
```

M1 已实现：

- 图片魔数/MIME/数量/大小/重复校验。
- 本地原图、模型和产物存储。
- SQLite 项目、图片、作业、阶段、产物表。
- Tripo 多视角任务：上传 -> 创建任务 -> 轮询 -> 下载 GLB。
- 作业失败重试与服务重启中断恢复。

M2 已实现：

- GLB 加载、Y-up→Z-up、毫米缩放和网格对齐。
- 表面体素化、闭合网格校验和外部泛洪实心填充。
- 最近三角面 UV/顶点色采样、内部颜色传播和 CIEDE2000 色卡匹配。
- `GET /api/v1/projects/{project_id}/voxel-preview` 确定性 XY 切片预览与稳定错误码。

真实 Tripo 联调需要 `.env` 中的 `TRIPO_API_KEY`。完整契约见 `docs/04-api-contract.md`。
