"""Placeholders for pipeline stages that are not wired yet.

ingest, reconstruct, and voxelize are implemented by ProjectService.run_job.
"""

from __future__ import annotations

from app.pipeline.orchestrator import PipelineContext, PipelineStageId, StageResult


def _not_implemented(stage: PipelineStageId, milestone: str):
    def handler(_context: PipelineContext) -> StageResult:
        raise NotImplementedError(f"{stage.value} 将在 {milestone} 实现")

    return handler


decompose = _not_implemented(PipelineStageId.DECOMPOSE, "M3")
joints = _not_implemented(PipelineStageId.JOINTS, "M4")
layout = _not_implemented(PipelineStageId.LAYOUT, "M5")
render = _not_implemented(PipelineStageId.RENDER, "M6")
export = _not_implemented(PipelineStageId.EXPORT, "M6")
validate = _not_implemented(PipelineStageId.VALIDATE, "M7-T1")
