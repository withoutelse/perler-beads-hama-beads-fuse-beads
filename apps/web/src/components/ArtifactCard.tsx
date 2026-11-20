import type { Artifact, ArtifactKind } from "../types/domain";

const iconByKind: Record<ArtifactKind, string> = {
  model_glb: "3D",
  design_json: "{}",
  layout_svg: "▦",
  layout_png: "▦",
  exploded_svg: "↗",
  three_view_svg: "◫",
  assembly_pdf: "PDF",
  bom_csv: "CSV",
  validation_json: "✓"
};

export function ArtifactCard({ artifact }: { artifact: Artifact }) {
  const ready = artifact.status === "ready";
  return (
    <article className={`artifact-card ${ready ? "" : "artifact-card--pending"}`}>
      <div className="artifact-icon">{iconByKind[artifact.kind]}</div>
      <div className="artifact-copy">
        <div className="artifact-heading">
          <strong>{artifact.title}</strong>
          <span className={`artifact-status ${ready ? "artifact-status--ready" : ""}`}>
            {ready ? "可下载" : "待生成"}
          </span>
        </div>
        <p>{artifact.description}</p>
        <div className="artifact-meta">
          <span>{artifact.filename}</span>
          <span>{artifact.sizeLabel}</span>
        </div>
      </div>
      {ready && artifact.downloadUrl ? (
        <a className="button button--small" href={artifact.downloadUrl} download>
          下载
        </a>
      ) : (
        <button className="button button--small" disabled type="button">
          待生成
        </button>
      )}
    </article>
  );
}
