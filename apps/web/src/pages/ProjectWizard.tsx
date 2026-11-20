import { useMemo, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";

import { api, ApiError } from "../api/client";
import { BeadSpecPicker } from "../components/BeadSpecPicker";
import { RouteGuardBanner } from "../components/RouteGuardBanner";
import type { BeadSize, BeadSpec, Job, Project } from "../types/domain";

const mosaicColors = ["orange", "cream", "white", "dark"];

const beadSpecs: Record<BeadSize, BeadSpec> = {
  "5mm": {
    size: "5mm",
    outerDiameterMm: 5,
    pitchMm: 5,
    heightMm: 5.1,
    holeDiameterMm: 2.2,
    boardMaxCellsX: 29,
    boardMaxCellsY: 29
  },
  "2.6mm": {
    size: "2.6mm",
    outerDiameterMm: 2.6,
    pitchMm: 2.6,
    heightMm: 2.8,
    holeDiameterMm: 1.0,
    boardMaxCellsX: 57,
    boardMaxCellsY: 57
  }
};

export function ProjectWizard({
  onStarted
}: {
  onStarted: (project: Project, job: Job) => void;
}) {
  const [name, setName] = useState("橙色小圆罐");
  const [beadSize, setBeadSize] = useState<BeadSize>("5mm");
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canStart = files.length >= 3 && !busy;
  const fileSummary = useMemo(
    () => files.slice(0, 4).map((file) => file.name),
    [files]
  );

  function handleFiles(nextFiles: FileList | null) {
    if (!nextFiles) return;
    setFiles(Array.from(nextFiles).slice(0, 12));
    setError(null);
  }

  function handleInput(event: ChangeEvent<HTMLInputElement>) {
    handleFiles(event.target.files);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    handleFiles(event.dataTransfer.files);
  }

  async function handleStart() {
    if (!canStart) return;
    setBusy(true);
    setError(null);
    try {
      const project = await api.createProject({
        name: name.trim() || "未命名拼豆项目",
        beadSpec: beadSpecs[beadSize]
      });
      const uploaded = await api.uploadImages(project.id, files);
      const job = await api.compileProject(uploaded.id);
      onStarted(uploaded, job);
    } catch (cause) {
      const message =
        cause instanceof ApiError
          ? `${cause.code}：${cause.message}`
          : cause instanceof Error
            ? cause.message
            : "创建项目失败，请稍后重试";
      setError(message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page-stack">
      <section className="hero">
        <div className="hero-card">
          <span className="eyebrow">MULTI-VIEW → 3D PERLER</span>
          <h1>把多视角照片，拆成可熨烫、可拼插的 3D 拼豆图纸。</h1>
          <p className="hero-lede">
            系统会重建模型、实心体素化，并按层带拆成环片、围板和十字骨架。每块板件都能独立熨烫，靠互补卡扣无胶组装。
          </p>
          <div className="hero-meta">
            <span>5mm / 2.6mm</span>
            <span>双面有孔</span>
            <span>免胶拼插</span>
            <span>PDF + 爆炸图</span>
          </div>
        </div>
        <div className="hero-visual" aria-hidden="true">
          <div className="hero-visual-label">DEMO OBJECT / 5mm</div>
          <div className="bead-mosaic">
            {Array.from({ length: 64 }, (_, index) => {
              const color = mosaicColors[(index * 7 + Math.floor(index / 8)) % mosaicColors.length];
              return <span key={index} className={`mosaic-dot mosaic-dot--${color}`} />;
            })}
          </div>
          <div className="hero-visual-footer">
            <span>P01 底环</span>
            <span>P02 围板</span>
            <span>P03 十字骨架</span>
          </div>
        </div>
      </section>

      <RouteGuardBanner />

      <div className="section-grid">
        <section className="panel">
          <div className="panel-header">
            <div>
              <span className="panel-kicker">01 / 输入</span>
              <h2>上传同一物体的多视角图片</h2>
            </div>
            <span className="panel-count">{files.length}/12</span>
          </div>
          <label className="field-label" htmlFor="project-name">
            项目名称
          </label>
          <input
            id="project-name"
            className="text-input"
            value={name}
            maxLength={120}
            onChange={(event) => setName(event.target.value)}
            placeholder="例如：橙色小圆罐"
          />
          <label
            className={`dropzone ${dragging ? "dropzone--active" : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
          >
            <input
              type="file"
              multiple
              accept="image/png,image/jpeg,image/webp"
              onChange={handleInput}
            />
            <span className="dropzone-icon">＋</span>
            <strong>拖入多视角图片</strong>
            <span>至少 3 张，建议 6–12 张；支持 JPG / PNG / WebP</span>
          </label>
          {files.length > 0 ? (
            <div className="file-list">
              {fileSummary.map((filename, index) => (
                <span key={`${filename}-${index}`} className="file-chip">
                  {filename}
                </span>
              ))}
              {files.length > 4 && <span className="file-chip">+{files.length - 4}</span>}
            </div>
          ) : (
            <p className="hint">M1 已接入 MIME 魔数校验、重复检测和本地对象存储。</p>
          )}
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <span className="panel-kicker">02 / 规格</span>
              <h2>选择拼豆规格</h2>
            </div>
          </div>
          <BeadSpecPicker value={beadSize} onChange={setBeadSize} />
          <div className="panel-divider" />
          <div className="option-row">
            <div>
              <strong>路线策略</strong>
              <p>按造型分件 + 双面有孔 + 免胶拼插</p>
            </div>
            <span className="route-mini">LOCKED</span>
          </div>
          <div className="option-row">
            <div>
              <strong>输出</strong>
              <p>展开网格图 · 爆炸装配图 · 三视图 · PDF · BOM</p>
            </div>
          </div>
          {error && (
            <div className="form-error" role="alert">
              {error}
            </div>
          )}
          <button
            className="button button--primary button--wide"
            disabled={!canStart}
            onClick={handleStart}
          >
            {busy ? "正在创建并上传…" : "开始生成图纸"}
          </button>
          {!canStart && !busy && <p className="hint">先上传至少 3 张图片。</p>}
        </section>
      </div>
    </div>
  );
}
