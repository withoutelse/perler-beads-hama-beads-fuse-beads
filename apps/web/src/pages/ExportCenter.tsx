import type { Artifact } from "../types/domain";
import { ArtifactCard } from "../components/ArtifactCard";

export function ExportCenter({ artifacts }: { artifacts: Artifact[] }) {
  const ready = artifacts.filter((artifact) => artifact.status === "ready").length;

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <span className="eyebrow">EXPORT</span>
          <h1>图纸与装配说明</h1>
          <p>展开网格图、爆炸装配图、三视图、PDF 和 BOM 都从同一份设计 JSON 生成。</p>
        </div>
        <div className="metric-card">
          <span>可下载产物</span>
          <strong>{ready}/{artifacts.length}</strong>
          <p>PDF 与三视图将在 M6 完成</p>
        </div>
      </section>

      {artifacts.length === 0 ? (
        <section className="panel">
          <p className="hint">暂无真实产物。完成 M1 重建后，这里会出现可下载的 GLB 模型。</p>
        </section>
      ) : (
        <section className="artifact-grid">
          {artifacts.map((artifact) => (
            <ArtifactCard key={artifact.id} artifact={artifact} />
          ))}
        </section>
      )}

      <section className="panel export-note">
        <div className="export-note-mark">1:1</div>
        <div>
          <h2>打印前先量校验尺</h2>
          <p>5mm 豆：10 格应为 50mm；2.6mm 豆：10 格应为 26mm。PDF 会带 1:1 校验尺和双面有孔烫法说明。</p>
        </div>
      </section>
    </div>
  );
}
