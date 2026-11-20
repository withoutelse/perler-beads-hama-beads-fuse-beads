import { useEffect, useMemo, useState } from "react";

import { api, ApiError } from "../api/client";
import type { Project, VoxelPreview, VoxelPreviewCell } from "../types/domain";

const DEFAULT_TARGET_HEIGHT_MM = 80;
const DEFAULT_DELTA_E_TOLERANCE = 6;

type UpAxis = "y" | "z";

interface PreviewOptions {
  targetHeightMm: number;
  deltaETolerance: number;
  sourceUpAxis: UpAxis;
}

interface SliceRequest {
  projectId: string;
  z: number;
}

interface PreviewError {
  code: string;
  message: string;
}

function toPreviewError(cause: unknown): PreviewError {
  if (cause instanceof ApiError) {
    return { code: cause.code, message: cause.message };
  }
  if (cause instanceof Error) {
    return { code: "VOXEL_PREVIEW_FAILED", message: cause.message };
  }
  return { code: "VOXEL_PREVIEW_FAILED", message: "读取体素切片失败" };
}

function formatMm(value: number): string {
  return `${value.toFixed(1)} mm`;
}

function normalizeNumber(value: number, fallback: number, minimum: number): number {
  return Number.isFinite(value) ? Math.max(minimum, value) : fallback;
}

export function DesignReview({ project }: { project: Project | null }) {
  const [preview, setPreview] = useState<VoxelPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<PreviewError | null>(null);
  const [targetHeightMm, setTargetHeightMm] = useState(DEFAULT_TARGET_HEIGHT_MM);
  const [deltaETolerance, setDeltaETolerance] = useState(DEFAULT_DELTA_E_TOLERANCE);
  const [sourceUpAxis, setSourceUpAxis] = useState<UpAxis>("y");
  const [appliedOptions, setAppliedOptions] = useState<PreviewOptions>({
    targetHeightMm: DEFAULT_TARGET_HEIGHT_MM,
    deltaETolerance: DEFAULT_DELTA_E_TOLERANCE,
    sourceUpAxis: "y"
  });
  const [sliceRequest, setSliceRequest] = useState<SliceRequest | null>(null);
  const [sliceDraft, setSliceDraft] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);

  const projectId = project?.id;
  const projectReady = project?.status === "ready";

  useEffect(() => {
    if (!projectId || !projectReady) {
      setPreview(null);
      setError(null);
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);
    setPreview(null);

    const requestedZ = sliceRequest?.projectId === projectId ? sliceRequest.z : undefined;
    api
      .getVoxelPreview(projectId, {
        z: requestedZ,
        targetHeightMm: appliedOptions.targetHeightMm,
        deltaETolerance: appliedOptions.deltaETolerance,
        sourceUpAxis: appliedOptions.sourceUpAxis
      })
      .then((next) => {
        if (cancelled) return;
        setPreview(next);
        setSliceDraft(next.sliceIndex);
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setError(toPreviewError(cause));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [appliedOptions, projectId, projectReady, reloadKey, sliceRequest]);

  const width = preview?.gridShape[0] ?? 0;
  const height = preview?.gridShape[1] ?? 0;
  const colorByCell = useMemo(() => {
    const map = new Map<string, VoxelPreviewCell>();
    preview?.cells.forEach((cell) => map.set(`${cell.x},${cell.y}`, cell));
    return map;
  }, [preview]);

  const cellSize = useMemo(() => {
    if (!width || !height) return 18;
    return Math.max(4, Math.min(22, Math.floor(620 / Math.max(width, height))));
  }, [height, width]);

  const legend = useMemo(() => {
    if (!preview) return [];
    return Object.entries(preview.colorCounts).sort(
      ([leftColor, leftCount], [rightColor, rightCount]) =>
        rightCount - leftCount || leftColor.localeCompare(rightColor)
    );
  }, [preview]);

  const gridCells = useMemo(() => {
    if (!preview) return [];
    const cells: JSX.Element[] = [];
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const cell = colorByCell.get(`${x},${y}`);
        cells.push(
          <span
            key={`${x},${y}`}
            className={`voxel-cell ${cell ? "voxel-cell--solid" : "voxel-cell--empty"}`}
            style={cell ? { backgroundColor: cell.hex } : undefined}
            title={cell ? `x=${x}, y=${y}, ${cell.color} ${cell.hex}` : `x=${x}, y=${y}, 空`}
          />
        );
      }
    }
    return cells;
  }, [colorByCell, height, preview, width]);

  function applyOptions() {
    setAppliedOptions({
      targetHeightMm: normalizeNumber(targetHeightMm, DEFAULT_TARGET_HEIGHT_MM, 1),
      deltaETolerance: normalizeNumber(deltaETolerance, DEFAULT_DELTA_E_TOLERANCE, 0),
      sourceUpAxis
    });
    setSliceRequest(null);
    setReloadKey((value) => value + 1);
  }

  function loadSlice(index: number) {
    if (!projectId || !preview) return;
    const next = Math.min(Math.max(index, 0), preview.sliceCount - 1);
    setSliceDraft(next);
    setSliceRequest({ projectId, z: next });
  }

  function retryPreview() {
    setReloadKey((value) => value + 1);
  }

  const sliceLabel = preview
    ? `z=${preview.sliceIndex} · ${preview.sliceIndex + 1}/${preview.sliceCount}`
    : "等待切片";

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <span className="eyebrow">VOXEL REVIEW · M2-T4</span>
          <h1>实心体素切片审阅</h1>
          <p>
            从 Tripo GLB 读取真实体素结果，逐层检查占用格、色号和物理尺寸。当前只做切片审阅，
            不把演示板件冒充成最终分件。
          </p>
        </div>
        <div className={`metric-card ${preview ? "metric-card--green" : ""}`}>
          <span>当前切片</span>
          <strong>{preview ? preview.occupiedCount : "—"}</strong>
          <p>
            {preview
              ? `${sliceLabel} · ${legend.length} 个色号`
              : projectReady
                ? "等待 GLB 体素结果"
                : "先完成 Tripo 重建"}
          </p>
        </div>
      </section>

      <div className="voxel-review-layout">
        <section className="panel voxel-preview-panel">
          <div className="panel-header">
            <div>
              <span className="panel-kicker">SLICE PREVIEW</span>
              <h2>{preview ? `第 ${preview.sliceIndex} 层 · XY 平面` : "体素网格"}</h2>
            </div>
            <span className="panel-count">{preview ? `${width}×${height}` : "—"}</span>
          </div>

          {loading && (
            <div className="voxel-empty" role="status">
              <span className="voxel-empty-mark">…</span>
              <strong>正在读取体素切片</strong>
              <p>正在归一化 GLB、填充实心体素并匹配色卡。</p>
            </div>
          )}

          {!loading && error && (
            <div className="voxel-empty voxel-empty--error" role="alert">
              <span className="voxel-empty-mark">!</span>
              <strong>{error.code}</strong>
              <p>{error.message}</p>
              <button className="button button--small" type="button" onClick={retryPreview}>
                重试
              </button>
            </div>
          )}

          {!loading && !error && !preview && (
            <div className="voxel-empty">
              <span className="voxel-empty-mark">◌</span>
              <strong>{project ? "还没有可审阅的体素结果" : "尚未创建项目"}</strong>
              <p>
                {project
                  ? "请先在流水线完成 ingest 与 reconstruct，生成 model.glb 后再回到设计审阅。"
                  : "先到项目向导上传 3–12 张多视角图片并启动编译。"}
              </p>
            </div>
          )}

          {!loading && !error && preview && (
            <>
              <div className="voxel-stage">
                <div className="voxel-axis voxel-axis--x">x →</div>
                <div
                  className="voxel-grid"
                  style={{
                    gridTemplateColumns: `repeat(${width}, ${cellSize}px)`,
                    gridAutoRows: `${cellSize}px`
                  }}
                  aria-label={`体素切片 z=${preview.sliceIndex}，${width} 列 × ${height} 行`}
                >
                  {gridCells}
                </div>
                <div className="voxel-axis voxel-axis--y">y ↓</div>
              </div>
              <div className="voxel-meta-grid">
                <div>
                  <span>网格尺寸</span>
                  <strong>{preview.gridShape.join(" × ")}</strong>
                </div>
                <div>
                  <span>物理范围</span>
                  <strong>{preview.gridExtentMm.map(formatMm).join(" × ")}</strong>
                </div>
                <div>
                  <span>切片占用</span>
                  <strong>{preview.occupiedCount} / {width * height} 格</strong>
                </div>
                <div>
                  <span>豆距 / 色号</span>
                  <strong>{formatMm(preview.pitchMm)} · {legend.length} 色</strong>
                </div>
              </div>
              <p className="voxel-note">
                坐标约定：x 向右、y 向深度、z 向上；切片按 z 从 0 到 {preview.sliceCount - 1}。
                空格透明，实心格使用色卡十六进制颜色。
              </p>
            </>
          )}
        </section>

        <div className="voxel-side-stack">
          <section className="panel">
            <div className="panel-header">
              <div>
                <span className="panel-kicker">NAVIGATION</span>
                <h2>切片导航</h2>
              </div>
              <span className="panel-count">{preview ? preview.sliceCount : "—"}</span>
            </div>
            {preview ? (
              <>
                <div className="voxel-slice-controls">
                  <button
                    className="button button--small"
                    type="button"
                    disabled={loading || preview.sliceIndex <= 0}
                    onClick={() => loadSlice(preview.sliceIndex - 1)}
                  >
                    ← 上一层
                  </button>
                  <button
                    className="button button--small"
                    type="button"
                    disabled={loading || preview.sliceIndex >= preview.sliceCount - 1}
                    onClick={() => loadSlice(preview.sliceIndex + 1)}
                  >
                    下一层 →
                  </button>
                </div>
                <label className="field-label" htmlFor="voxel-slice-range">
                  跳转切片 z
                </label>
                <input
                  id="voxel-slice-range"
                  className="voxel-range"
                  type="range"
                  min={0}
                  max={Math.max(0, preview.sliceCount - 1)}
                  value={sliceDraft}
                  disabled={loading}
                  onChange={(event) => setSliceDraft(Number(event.target.value))}
                />
                <div className="voxel-range-meta">
                  <span>z={sliceDraft}</span>
                  <button
                    className="button button--small"
                    type="button"
                    disabled={loading}
                    onClick={() => loadSlice(sliceDraft)}
                  >
                    查看该层
                  </button>
                </div>
              </>
            ) : (
              <p className="hint">生成体素结果后可逐层切换。</p>
            )}

            <div className="panel-divider" />
            <div className="panel-header">
              <div>
                <span className="panel-kicker">SAMPLING</span>
                <h2>采样参数</h2>
              </div>
            </div>
            <label className="field-label" htmlFor="voxel-target-height">
              目标高度（mm）
            </label>
            <input
              id="voxel-target-height"
              className="text-input"
              type="number"
              min={1}
              step={1}
              value={targetHeightMm}
              onChange={(event) => setTargetHeightMm(Number(event.target.value))}
            />
            <label className="field-label" htmlFor="voxel-delta-e">
              色差容差 ΔE
            </label>
            <input
              id="voxel-delta-e"
              className="text-input"
              type="number"
              min={0}
              step={0.5}
              value={deltaETolerance}
              onChange={(event) => setDeltaETolerance(Number(event.target.value))}
            />
            <label className="field-label" htmlFor="voxel-up-axis">
              源模型上轴
            </label>
            <select
              id="voxel-up-axis"
              className="text-input"
              value={sourceUpAxis}
              onChange={(event) => setSourceUpAxis(event.target.value as UpAxis)}
            >
              <option value="y">Y-up（Tripo / glTF 常见）</option>
              <option value="z">Z-up</option>
            </select>
            <button
              className="button button--primary button--wide"
              type="button"
              disabled={!projectReady || loading}
              onClick={applyOptions}
            >
              重新计算体素
            </button>
          </section>

          <section className="panel">
            <div className="panel-header">
              <div>
                <span className="panel-kicker">PALETTE</span>
                <h2>色号图例</h2>
              </div>
              <span className="panel-count">{legend.length}</span>
            </div>
            {legend.length > 0 && preview ? (
              <div className="voxel-legend">
                {legend.map(([colorId, count]) => (
                  <div className="voxel-legend-item" key={colorId}>
                    <span
                      className="voxel-swatch"
                      style={{ backgroundColor: preview.palette[colorId] ?? "#999999" }}
                    />
                    <span className="voxel-legend-copy">
                      <strong>{colorId}</strong>
                      <small>{preview.palette[colorId] ?? "#999999"}</small>
                    </span>
                    <span className="voxel-legend-count">
                      {count}
                      <small>{preview.occupiedCount > 0 ? `${Math.round((count / preview.occupiedCount) * 100)}%` : "0%"}</small>
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="hint">当前切片没有可统计的色号。</p>
            )}
            <div className="panel-divider" />
            <div className="route-mini-row">
              <span>路线守卫</span>
              <strong>shape_partitioned_double_sided_hole_glue_free</strong>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
