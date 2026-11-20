from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from app.domain.bead import BeadSpec


class PipelineStageId(str, Enum):
    INGEST = "ingest"
    RECONSTRUCT = "reconstruct"
    VOXELIZE = "voxelize"
    DECOMPOSE = "decompose"
    JOINTS = "joints"
    LAYOUT = "layout"
    RENDER = "render"
    EXPORT = "export"
    VALIDATE = "validate"


@dataclass(frozen=True, slots=True)
class StageSpec:
    id: PipelineStageId
    label: str
    description: str


STAGE_SPECS: tuple[StageSpec, ...] = (
    StageSpec(PipelineStageId.INGEST, "输入校验", "校验图片、豆规格和项目参数"),
    StageSpec(PipelineStageId.RECONSTRUCT, "3D 重建", "调用 Tripo 生成 3D 模型"),
    StageSpec(PipelineStageId.VOXELIZE, "实心体素化", "将模型转为实心体素网格"),
    StageSpec(PipelineStageId.DECOMPOSE, "层带/板件分解", "提取层带、轮廓和板件"),
    StageSpec(
        PipelineStageId.JOINTS,
        "卡扣合成",
        "生成互补舌槽并应用双面有孔烫法",
    ),
    StageSpec(PipelineStageId.LAYOUT, "2D 排版", "展开板件并生成 BOM"),
    StageSpec(PipelineStageId.RENDER, "图形渲染", "生成展开图、爆炸图和三视图"),
    StageSpec(PipelineStageId.EXPORT, "PDF/BOM 导出", "输出可打印产物"),
    StageSpec(PipelineStageId.VALIDATE, "门禁校验", "运行路线和可制造性门禁"),
)


@dataclass(frozen=True, slots=True)
class PipelineContext:
    project_id: str
    bead_spec: BeadSpec
    image_paths: tuple[Path, ...]
    work_dir: Path
    options: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StageResult:
    stage: PipelineStageId
    status: str
    message: str = ""
    artifact_paths: tuple[Path, ...] = ()


StageHandler = Callable[[PipelineContext], StageResult]


class PipelineOrchestrator:
    def __init__(self, handlers: Mapping[PipelineStageId, StageHandler] | None = None) -> None:
        self._handlers = dict(handlers or {})

    def run(self, context: PipelineContext) -> tuple[StageResult, ...]:
        results: list[StageResult] = []
        for spec in STAGE_SPECS:
            handler = self._handlers.get(spec.id)
            if handler is None:
                results.append(StageResult(spec.id, "pending", "尚未实现"))
                continue
            results.append(handler(context))
        return tuple(results)
