import type { PipelineStage, StageStatus } from "../types/domain";

const statusLabel: Record<StageStatus, string> = {
  pending: "待开始",
  queued: "排队中",
  running: "进行中",
  succeeded: "完成",
  failed: "失败"
};

export function PipelineTimeline({ stages }: { stages: PipelineStage[] }) {
  return (
    <ol className="timeline">
      {stages.map((stage, index) => (
        <li key={stage.id} className={`timeline-item timeline-item--${stage.status}`}>
          <div className="timeline-rail">
            <span className="timeline-dot">{stage.status === "succeeded" ? "✓" : index + 1}</span>
            {index < stages.length - 1 && <span className="timeline-line" />}
          </div>
          <div className="timeline-body">
            <div className="timeline-heading">
              <strong>{stage.label}</strong>
              <span className="timeline-status">{statusLabel[stage.status]}</span>
            </div>
            <p>{stage.description}</p>
            {stage.status === "running" && (
              <div className="progress-track" aria-label={`${stage.label} 进度 ${stage.progress}%`}>
                <span style={{ width: `${stage.progress}%` }} />
              </div>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
