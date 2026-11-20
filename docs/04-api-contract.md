# API 契约

Base URL：`/api/v1`。除文件下载外，请求和响应均为 JSON。当前只面向单人本地自用，不做登录、多用户、权限和配额。

错误统一格式：

```json
{
  "error": {
    "code": "PLATE_DISCONNECTED",
    "message": "P03 不是 4-连通板件",
    "details": {"plate_id": "P03"}
  }
}
```

## 1. 健康检查

### `GET /health`

```json
{"status": "ok", "service": "pindou-studio-api", "version": "0.1.0"}
```

## 2. 创建项目

### `POST /projects`

```json
{
  "name": "橙色小圆罐",
  "bead_spec": {
    "size": "5mm",
    "outer_diameter_mm": 5.0,
    "pitch_mm": 5.0,
    "height_mm": 5.1,
    "hole_diameter_mm": 2.2,
    "board_max_cells_x": 29,
    "board_max_cells_y": 29
  }
}
```

响应 `201`：

```json
{
  "id": "prj_7f3a2c1b9d4e",
  "name": "橙色小圆罐",
  "status": "draft",
  "image_count": 0,
  "bead_spec": {
    "size": "5mm",
    "outer_diameter_mm": 5.0,
    "pitch_mm": 5.0,
    "height_mm": 5.1,
    "hole_diameter_mm": 2.2,
    "board_max_cells_x": 29,
    "board_max_cells_y": 29
  },
  "route_policy": "shape_partitioned_double_sided_hole_glue_free",
  "created_at": "2026-11-19T10:00:00+00:00",
  "updated_at": "2026-11-19T10:00:00+00:00",
  "images": []
}
```

## 3. 上传多视角图片

### `POST /projects/{project_id}/images`

`multipart/form-data`：

- `files`：1–12 张图片，字段可重复。
- `view`：可选，`front|back|left|right|top|bottom|unknown`，默认 `unknown`。

支持 JPG、PNG、WebP。服务端会校验魔数、Content-Type、数量、单张 20 MB、总大小 100 MB、重复 SHA-256，并清洗文件名。

响应 `200`：更新后的项目。`images` 中每张图包含：

```json
{
  "id": "img_001",
  "filename": "front.jpg",
  "content_type": "image/jpeg",
  "size_bytes": 123456,
  "sha256": "…",
  "view": "front",
  "relative_path": "projects/prj_7f3a2c1b9d4e/images/img_001_front.jpg"
}
```

错误：

- `400 INVALID_IMAGE_TYPE`
- `400 INVALID_IMAGE_VIEW`
- `400 DUPLICATE_IMAGE`
- `400 TOO_MANY_IMAGES`
- `413 IMAGE_TOO_LARGE`
- `413 TOTAL_IMAGES_TOO_LARGE`

## 4. 启动编译

### `POST /projects/{project_id}/compile`

```json
{
  "route_policy": "shape_partitioned_double_sided_hole_glue_free",
  "options": {
    "target_height_mm": 80,
    "color_palette": "perler-standard",
    "delta_e_tolerance": 6.0,
    "max_plate_cells": 29
  }
}
```

响应 `202`：作业已排队。M2-T5 执行 `ingest`、`reconstruct` 和 `voxelize` 三个阶段；`decompose` 及后续阶段保持 `queued`，由 M3–M7 接入。`stages` 始终返回完整阶段列表。

```json
{
  "id": "job_9a1b2c3d4e5f",
  "project_id": "prj_7f3a2c1b9d4e",
  "status": "queued",
  "stages": [
    {"id": "ingest", "label": "输入校验", "status": "queued", "progress": 0, "message": "校验图片、豆规格和项目参数"},
    {"id": "reconstruct", "label": "3D 重建", "status": "queued", "progress": 0, "message": "调用 Tripo 生成 3D 模型"},
    {"id": "voxelize", "label": "实心体素化", "status": "queued", "progress": 0, "message": "将模型转为实心体素网格"},
    {"id": "decompose", "label": "层带/板件分解", "status": "queued", "progress": 0, "message": "提取层带、轮廓和板件"},
    {"id": "joints", "label": "卡扣合成", "status": "queued", "progress": 0, "message": "生成互补舌槽并应用双面有孔烫法"},
    {"id": "layout", "label": "2D 排版", "status": "queued", "progress": 0, "message": "展开板件并生成 BOM"},
    {"id": "render", "label": "图形渲染", "status": "queued", "progress": 0, "message": "生成展开图、爆炸图和三视图"},
    {"id": "export", "label": "PDF/BOM 导出", "status": "queued", "progress": 0, "message": "输出可打印产物"},
    {"id": "validate", "label": "门禁校验", "status": "queued", "progress": 0, "message": "运行路线和可制造性门禁"}
  ],
  "created_at": "2026-11-19T10:01:00+00:00",
  "updated_at": "2026-11-19T10:01:00+00:00",
  "error": null,
  "error_code": null,
  "error_details": {}
}
```

至少需要 3 张图片。若项目已有 `queued` 或 `running` 作业，会返回该作业，避免重复调用 Tripo。

## 5. 查询作业

### `GET /jobs/{job_id}`

```json
{
  "id": "job_9a1b2c3d4e5f",
  "project_id": "prj_7f3a2c1b9d4e",
  "status": "running",
  "stages": [
    {"id": "ingest", "label": "输入校验", "status": "succeeded", "progress": 100, "message": "已校验 8 张多视角图片"},
    {"id": "reconstruct", "label": "3D 重建", "status": "succeeded", "progress": 100, "message": "Tripo 重建完成，GLB 已保存"},
    {"id": "voxelize", "label": "实心体素化", "status": "running", "progress": 0, "message": "正在执行实心体素化和色卡匹配"},
    {"id": "decompose", "label": "层带/板件分解", "status": "queued", "progress": 0, "message": "提取层带、轮廓和板件"},
    {"id": "joints", "label": "卡扣合成", "status": "queued", "progress": 0, "message": "生成互补舌槽并应用双面有孔烫法"},
    {"id": "layout", "label": "2D 排版", "status": "queued", "progress": 0, "message": "展开板件并生成 BOM"},
    {"id": "render", "label": "图形渲染", "status": "queued", "progress": 0, "message": "生成展开图、爆炸图和三视图"},
    {"id": "export", "label": "PDF/BOM 导出", "status": "queued", "progress": 0, "message": "输出可打印产物"},
    {"id": "validate", "label": "门禁校验", "status": "queued", "progress": 0, "message": "运行路线和可制造性门禁"}
  ],
  "created_at": "2026-11-19T10:01:00+00:00",
  "updated_at": "2026-11-19T10:02:00+00:00",
  "error": null,
  "error_code": null,
  "error_details": {}
}
```

作业状态：`queued -> running -> succeeded | failed | cancelled`。服务重启时，遗留的 `queued/running` 作业会被标记为 `failed`，错误码 `JOB_INTERRUPTED`，可重试。

## 6. 重试作业

### `POST /jobs/{job_id}/retry`

只允许 `failed` 或 `cancelled` 作业。创建新作业并复用已有图片；若项目已有可用 `model_glb`，不会重复调用 Tripo，只重跑 `voxelize`。没有可用模型时才重新执行重建。

响应 `202`，结构同 `GET /jobs/{job_id}`。

错误：`400 JOB_NOT_RETRYABLE`。

## 7. 产物

### `GET /projects/{project_id}/artifacts`

```json
[
  {
    "id": "art_model_glb_123456789abc",
    "kind": "model_glb",
    "filename": "model.glb",
    "content_type": "model/gltf-binary",
    "size_bytes": 48210,
    "download_url": "/api/v1/projects/prj_7f3a2c1b9d4e/artifacts/art_model_glb_123456789abc"
  },
  {
    "id": "art_voxel_npz_08cacf2e4e2fff54e8cd2c8e",
    "kind": "voxel_npz",
    "filename": "voxel_08cacf2e4e2fff54e8cd2c8ee91d7d4f9ee65378d693c04f5800ca5345505cab.npz",
    "content_type": "application/octet-stream",
    "size_bytes": 2048,
    "download_url": "/api/v1/projects/prj_7f3a2c1b9d4e/artifacts/art_voxel_npz_08cacf2e4e2fff54e8cd2c8e"
  }
]
```

### `GET /projects/{project_id}/artifacts/{artifact_id}`

返回文件流，设置 `Content-Disposition: attachment`。

产物类型：

| kind | 说明 | 里程碑 |
| --- | --- | --- |
| `model_glb` | Tripo 重建的 GLB 原始模型 | M1 |
| `voxel_npz` | 实心体素、色号与采样参数的压缩 NPZ 产物 | M2-T5 |
| `design_json` | 完整设计 JSON | M2+ |
| `layout_svg` | 展开网格图 | M5 |
| `layout_png` | 展开网格预览 | M5 |
| `exploded_svg` | 爆炸装配图 | M6 |
| `three_view_svg` | 成品三视图 | M6 |
| `assembly_pdf` | 可打印装配说明 | M6 |
| `bom_csv` | 色号/颗数清单 | M5 |
| `validation_json` | 校验报告 | M7 |

## 8. 体素切片预览

### `GET /projects/{project_id}/voxel-preview`

读取项目最新的 `model_glb` 产物，返回一个确定性 XY 切片。接口按模型和采样参数查找 `voxel_npz`：首次请求构建并持久化，后续切片导航直接读取缓存。该接口只做审阅，不写入最终设计产物。

查询参数：

- `z`：可选，切片索引，范围 `0 <= z < slice_count`；省略时取中间层 `depth // 2`。
- `target_height_mm`：可选，目标高度毫米，默认 `80.0`，必须大于 0。
- `source_up_axis`：可选，`y` 或 `z`，默认 `y`（Tripo/glTF 常见 Y-up）。
- `delta_e_tolerance`：可选，色差容差，默认 `6.0`，不能为负数。

响应 `200`：

```json
{
  "project_id": "prj_7f3a2c1b9d4e",
  "artifact_id": "art_model_glb_123456789abc",
  "grid_shape": [3, 9, 6],
  "grid_extent_mm": [15.0, 45.0, 30.0],
  "pitch_mm": 5.0,
  "slice_index": 3,
  "slice_count": 6,
  "occupied_count": 27,
  "color_counts": {"charcoal": 27},
  "palette": {"charcoal": "#3b3b3b"},
  "cells": [
    {"x": 0, "y": 0, "color": "charcoal", "hex": "#3b3b3b"}
  ]
}
```

坐标约定：

- `grid_shape = [width, height, depth]`，分别对应世界坐标 `x/y/z` 的格数。
- `cells` 只包含当前 `z` 切片的实心格，`x` 向右、`y` 向深度。
- `grid_extent_mm` 是归一化后的物理包围盒，单位毫米。
- `artifact_id` 是源 `model_glb` 产物 ID；体素缓存产物通过项目产物列表获取。
- 空切片返回 `occupied_count = 0` 和空 `cells`，不返回演示数据。

错误码：

| 错误码 | HTTP | 说明 |
| --- | --- | --- |
| `MODEL_ARTIFACT_NOT_FOUND` | 404 | 项目还没有 `model_glb` 产物 |
| `MODEL_ARTIFACT_MISSING` | 404 | 产物记录存在但文件丢失 |
| `VOXEL_INVALID_TARGET_HEIGHT` | 400 | `target_height_mm <= 0` |
| `VOXEL_INVALID_TOLERANCE` | 400 | `delta_e_tolerance < 0` |
| `VOXEL_INVALID_UP_AXIS` | 400 | `source_up_axis` 不是 `y` 或 `z` |
| `VOXEL_UNSUPPORTED_PALETTE` | 400 | 请求了不支持的色卡 |
| `VOXEL_SLICE_OUT_OF_RANGE` | 400 | `z` 超出 `[0, slice_count)` |
| `VOXEL_ARTIFACT_MISSING` | 500 | 体素缓存文件不存在 |
| `VOXEL_ARTIFACT_READ_FAILED` | 500 | 体素缓存无法读取或结构损坏 |
| `VOXEL_ARTIFACT_WRITE_FAILED` | 500 | 体素缓存无法写入 |
| `VOXEL_ARTIFACT_SCHEMA_UNSUPPORTED` | 500 | 体素产物 schema 版本不受支持 |
| `VOXEL_ARTIFACT_INVALID_GRID` | 500 | 体素网格尺寸无效 |
| `VOXEL_ARTIFACT_INVALID_PITCH` | 500 | 体素间距无效 |
| `VOXEL_ARTIFACT_INVALID_EXTENT` | 500 | 体素物理边界无效 |
| `VOXEL_ARTIFACT_INVALID_VOXEL` | 500 | 体素越界或重复 |
| `VOXEL_ARTIFACT_INVALID_COLOR_MAP` | 500 | 颜色索引/色号映射不一致 |
| `NORMALIZATION_NOT_WATERTIGHT` | 500 | GLB 不是闭合网格，不能实心化 |
| `TEXTURE_*` | 500 | 纹理/顶点色采样失败，具体见算法规范 |
| `VOXEL_PREVIEW_FAILED` | 500 | 未预期的预览失败 |

## 9. 规划中的接口

以下接口属于 M2+，当前未实现：

- `GET /projects/{project_id}/design`
- `POST /projects/{project_id}/validate`

## 10. 作业阶段

| id | 标签 | 当前状态 |
| --- | --- | --- |
| `ingest` | 输入校验 | M1 已实现 |
| `reconstruct` | 3D 重建 | M1 已实现 |
| `voxelize` | 实心体素化 | M2-T5 已接入作业流水线，产物持久化为 `voxel_npz` 并支持缓存复用 |
| `decompose` | 层带/板件分解 | M3 |
| `joints` | 卡扣合成 | M4 |
| `layout` | 2D 排版 | M5 |
| `render` | 图形渲染 | M6 |
| `export` | PDF/BOM 导出 | M6 |
| `validate` | 门禁校验 | M7 |

## 11. 错误码

| 错误码 | HTTP | 说明 |
| --- | --- | --- |
| `NOT_FOUND` | 404 | 项目/作业/产物不存在 |
| `VALIDATION_ERROR` | 422 | 请求参数未通过 Pydantic 校验 |
| `INVALID_INPUT` | 400 | 通用输入错误 |
| `INVALID_IMAGE_TYPE` | 400 | 图片格式不支持或 MIME 不一致 |
| `INVALID_IMAGE_VIEW` | 400 | 视角标签无效 |
| `DUPLICATE_IMAGE` | 400 | 重复图片 |
| `TOO_MANY_IMAGES` | 400 | 超过 12 张 |
| `IMAGE_TOO_LARGE` | 413 | 单张大小超限 |
| `TOTAL_IMAGES_TOO_LARGE` | 413 | 总大小超限 |
| `ROUTE_VIOLATION` | 400 | 路线策略不合规 |
| `JOB_NOT_RETRYABLE` | 400 | 作业状态不可重试 |
| `JOB_INTERRUPTED` | 500 | 服务重启导致作业中断 |
| `TRIPO_NOT_CONFIGURED` | 500 | 未配置 Tripo 密钥 |
| `TRIPO_NEEDS_MULTIVIEW` | 500 | 图片不足 3 张 |
| `TRIPO_NETWORK_ERROR` | 500 | Tripo 网络错误 |
| `TRIPO_HTTP_ERROR` | 500 | Tripo 返回错误 |
| `TRIPO_TIMEOUT` | 500 | Tripo 任务超时 |
| `TRIPO_RECONSTRUCTION_FAILED` | 500 | Tripo 重建失败 |
| `TRIPO_MODEL_PATH_INVALID` | 500 | 模型文件不在项目存储目录 |
| `RECONSTRUCTION_FAILED` | 500 | 未预期的重建失败 |
| `MODEL_ARTIFACT_NOT_FOUND` | 404 | 项目还没有可预览的 GLB 模型 |
| `MODEL_ARTIFACT_MISSING` | 404 | GLB 产物文件不存在 |
| `VOXEL_INVALID_TARGET_HEIGHT` | 400 | 体素预览目标高度无效 |
| `VOXEL_INVALID_TOLERANCE` | 400 | 体素预览色差容差无效 |
| `VOXEL_INVALID_UP_AXIS` | 400 | 体素上轴无效 |
| `VOXEL_UNSUPPORTED_PALETTE` | 400 | 体素色卡不受支持 |
| `VOXEL_SLICE_OUT_OF_RANGE` | 400 | 体素切片索引越界 |
| `VOXEL_PREVIEW_FAILED` | 500 | 体素预览未预期失败 |
| `VOXELIZATION_FAILED` | 500 | 体素化作业未预期失败 |
| `VOXEL_ARTIFACT_MISSING` | 500 | 体素产物文件不存在 |
| `VOXEL_ARTIFACT_READ_FAILED` | 500 | 体素产物无法读取 |
| `VOXEL_ARTIFACT_WRITE_FAILED` | 500 | 体素产物无法写入 |
| `VOXEL_ARTIFACT_SCHEMA_UNSUPPORTED` | 500 | 体素产物版本不受支持 |
| `VOXEL_ARTIFACT_INVALID_GRID` | 500 | 体素网格尺寸无效 |
| `VOXEL_ARTIFACT_INVALID_PITCH` | 500 | 体素间距无效 |
| `VOXEL_ARTIFACT_INVALID_EXTENT` | 500 | 体素物理边界无效 |
| `VOXEL_ARTIFACT_INVALID_VOXEL` | 500 | 体素越界或重复 |
| `VOXEL_ARTIFACT_INVALID_COLOR_MAP` | 500 | 体素颜色映射无效 |
| `NORMALIZATION_NOT_WATERTIGHT` | 500 | 网格非闭合，不能实心化 |
| `TEXTURE_*` | 500 | 纹理/顶点色采样失败 |

> M1/M2 的错误码先沿用当前服务层映射；M7 会把外部错误统一映射为更细的 HTTP 状态和前端可操作提示。

## 12. 本地持久化

- SQLite：`DATABASE_URL=sqlite:///./storage/pindou.db`
- 文件：`STORAGE_DIR=./storage`
- 表：`projects`、`images`、`jobs`、`job_stages`、`artifacts`
- 服务启动时自动建表，并把上次进程遗留的 `queued/running` 作业标记为可重试失败。

## 13. Tripo 配置

```env
TRIPO_API_BASE_URL=https://api.tripo3d.ai/v2/openapi
TRIPO_API_KEY=
TRIPO_MODEL_VERSION=v2.5-20250123
TRIPO_POLL_INTERVAL_S=2.0
TRIPO_TASK_TIMEOUT_S=600
TRIPO_REQUEST_TIMEOUT_S=120
```

API Key 只存在服务端，不下发前端。真实接口字段和模型版本尚未用账号验证；若不同，只调整 `apps/api/app/pipeline/adapters/tripo.py`。
