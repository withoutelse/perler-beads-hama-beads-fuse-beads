import { useEffect, useState } from "react";

import { api, ApiError } from "./api/client";
import { DesignReview } from "./pages/DesignReview";
import { ExportCenter } from "./pages/ExportCenter";
import { PipelineView } from "./pages/PipelineView";
import { ProjectWizard } from "./pages/ProjectWizard";
import { demoStages } from "./mock/demo";
import type {
  Artifact,
  Job,
  PipelineStage,
  Project,
  ProjectStatus,
  ViewId
} from "./types/domain";

const navItems: Array<{ id: ViewId; label: string; hint: string; icon: string }> = [
  { id: "project", label: "项目向导", hint: "上传与规格", icon: "＋" },
  { id: "pipeline", label: "流水线", hint: "阶段与日志", icon: "▦" },
  { id: "design", label: "设计审阅", hint: "体素与切片", icon: "◈" },
  { id: "export", label: "导出中心", hint: "图纸与 PDF", icon: "↗" }
];

const idleStages: PipelineStage[] = demoStages.map((stage) => ({
  ...stage,
  status: "pending" as const,
  progress: 0,
  description: "等待编译"
}));

const statusLabels: Record<ProjectStatus, string> = {
  draft: "草稿",
  queued: "排队中",
  running: "运行中",
  ready: "已就绪",
  failed: "失败"
};

export default function App() {
  const [view, setView] = useState<ViewId>("project");
  const [project, setProject] = useState<Project | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!job || (job.status !== "queued" && job.status !== "running")) return;

    let cancelled = false;
    let timer: number | undefined;

    const poll = async () => {
      try {
        const next = await api.getJob(job.id);
        if (cancelled) return;
        setJob(next);
        setProject((current) => {
          if (!current) return current;
          if (next.status === "succeeded") return { ...current, status: "ready" };
          if (next.status === "failed") return { ...current, status: "failed" };
          return { ...current, status: next.status === "queued" ? "queued" : "running" };
        });
        if (next.status === "succeeded") {
          try {
            const realArtifacts = await api.listArtifacts(next.projectId);
            if (!cancelled) setArtifacts(realArtifacts);
          } catch (cause) {
            if (!cancelled) {
              setError(cause instanceof Error ? cause.message : "读取产物失败");
            }
          }
        }
        if (next.status === "queued" || next.status === "running") {
          timer = window.setTimeout(poll, 1200);
        }
      } catch (cause) {
        if (cancelled) return;
        setError(cause instanceof Error ? cause.message : "轮询作业失败");
        timer = window.setTimeout(poll, 2500);
      }
    };

    timer = window.setTimeout(poll, 800);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [job?.id, job?.status]);

  function handleStarted(nextProject: Project, nextJob: Job) {
    setProject(nextProject);
    setJob(nextJob);
    setArtifacts([]);
    setError(null);
    setView("pipeline");
  }

  async function handleRetry() {
    if (!job) return;
    setError(null);
    try {
      const next = await api.retryJob(job.id);
      setJob(next);
      setArtifacts([]);
      setProject((current) => (current ? { ...current, status: "queued" } : current));
      setView("pipeline");
    } catch (cause) {
      setError(cause instanceof ApiError ? `${cause.code}：${cause.message}` : "重试失败");
    }
  }

  const projectStatus: ProjectStatus = project?.status ?? "draft";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">拼</div>
          <div>
            <div className="brand-title">PinDou Studio</div>
            <div className="brand-subtitle">拼豆工坊 · 3D 图纸</div>
          </div>
        </div>

        <nav className="nav" aria-label="主导航">
          {navItems.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-item ${view === item.id ? "nav-item--active" : ""}`}
              onClick={() => setView(item.id)}
            >
              <span className="nav-icon">{item.icon}</span>
              <span>
                <strong>{item.label}</strong>
                <small>{item.hint}</small>
              </span>
            </button>
          ))}
        </nav>

        <div className="sidebar-note">
          <span className="sidebar-note-label">M2 · VOXEL SLICE</span>
          <p>真实 GLB 已完成归一化、实心体素化与色卡匹配。设计审阅页可逐层检查占用格和色号。</p>
          <div className="sidebar-note-rule" />
          <span className="sidebar-note-foot">ROUTE LOCKED</span>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div>
            <div className="breadcrumb">项目 / {project?.name ?? "尚未创建项目"}</div>
            <div className="topbar-title">3D 拼豆设计工作台</div>
          </div>
          <div className="topbar-actions">
            <span className={`status-pill status-pill--${projectStatus}`}>
              {statusLabels[projectStatus]}
            </span>
            <button className="button button--ghost" type="button" onClick={() => setView("project")}>
              新建项目
            </button>
          </div>
        </header>

        <main className="content">
          {error && (
            <div className="app-error" role="alert">
              {error}
            </div>
          )}
          {view === "project" && <ProjectWizard onStarted={handleStarted} />}
          {view === "pipeline" && (
            <PipelineView
              stages={job?.stages ?? idleStages}
              job={job}
              onNext={() => setView("design")}
              onRetry={handleRetry}
            />
          )}
          {view === "design" && <DesignReview project={project} />}
          {view === "export" && <ExportCenter artifacts={artifacts} />}
        </main>
      </div>
    </div>
  );
}
