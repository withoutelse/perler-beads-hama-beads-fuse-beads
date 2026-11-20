import type { Job, PipelineStage } from "../types/domain";
import { PipelineTimeline } from "../components/PipelineTimeline";

const jobStatusLabel: Record<Job["status"], string> = {
  queued: "排队中",
  running: "运行中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消"
};

function formatTime(value: string | undefined): string {
  if (!value) return "--:--:--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--:--:--";
  return date.toLocaleTimeString("zh-CN", { hour12: false });
}

export function PipelineView({
  stages,
  job,
  onNext,
  onRetry
}: {
  stages: PipelineStage[];
  job: Job | null;
  onNext: () => void;
  onRetry: () => void;
}) {
  const completed = stages.filter((stage) => stage.status === "succeeded").length;
  const progress = stages.length === 0 ? 0 : Math.round((completed / stages.length) * 100);
  const visibleStages = stages.filter((stage) => stage.status !== "pending").slice(-6);
  const canReview = job?.status === "succeeded";
  const canRetry = job?.status === "failed";

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <span className="eyebrow">PIPELINE</span>
          <h1>从图片到可制造图纸</h1>
          <p>每个阶段都有明确输入/输出；失败可从最近的成功阶段重跑，不重复调用 Tripo。</p>
        </div>
        <div className="metric-card">
          <span>流水线进度</span>
          <strong>{progress}%</strong>
          <div className="progress-track">
            <span style={{ width: `${progress}%` }} />
          </div>
        </div>
      </section>

      {job?.error && (
        <div className="form-error" role="alert">
          <strong>{job.errorCode ?? "JOB_FAILED"}</strong>：{job.error}
        </div>
      )}

      <div className="pipeline-layout">
        <section className="panel">
          <div className="panel-header">
            <div>
              <span className="panel-kicker">STAGES</span>
              <h2>阶段时间线</h2>
            </div>
            <span className="panel-count">{completed}/{stages.length}</span>
          </div>
          <PipelineTimeline stages={stages} />
        </section>

        <section className="panel panel--dark">
          <div className="panel-header panel-header--dark">
            <div>
              <span className="panel-kicker">LIVE LOG</span>
              <h2>运行日志</h2>
            </div>
            <span className="live-dot">{job ? jobStatusLabel[job.status] : "STANDBY"}</span>
          </div>
          <div className="log-lines">
            {visibleStages.length === 0 ? (
              <p>等待编译。上传至少 3 张多视角图片后，Tripo 任务会在这里显示。</p>
            ) : (
              visibleStages.map((stage) => (
                <p key={stage.id} className={stage.status === "running" ? "log-active" : ""}>
                  <span>{formatTime(job?.updatedAt)}</span>
                  {stage.label}：{stage.description || stage.message || "等待中"}
                </p>
              ))
            )}
          </div>
          <div className="log-note">
            路线守卫：<strong>{job ? "PASS" : "STANDBY"}</strong> · 禁止特征：未出现
          </div>
        </section>
      </div>

      <div className="action-row">
        <span className="hint">
          {canReview
            ? "M1 重建已完成。后续里程碑会基于 GLB 生成体素和板件。"
            : canRetry
              ? "作业失败，可重试；不会重复上传已有图片。"
              : "作业运行中，请等待阶段完成。"}
        </span>
        {canRetry ? (
          <button className="button button--primary" type="button" onClick={onRetry}>
            重试作业
          </button>
        ) : (
          <button
            className="button button--primary"
            type="button"
            onClick={onNext}
            disabled={!canReview}
          >
            查看设计审阅
          </button>
        )}
      </div>
    </div>
  );
}
