import type {
  Artifact,
  ArtifactKind,
  BeadSpec,
  Job,
  PipelineStage,
  Project,
  ProjectImage,
  VoxelPreview,
  VoxelPreviewCell,
  VoxelPreviewOptions
} from "../types/domain";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

interface ApiBeadSpec {
  size: "5mm" | "2.6mm";
  outer_diameter_mm: number;
  pitch_mm: number;
  height_mm: number;
  hole_diameter_mm: number;
  board_max_cells_x: number;
  board_max_cells_y: number;
}

interface ApiImage {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  view: string;
  relative_path: string;
}

interface ApiProject {
  id: string;
  name: string;
  status: string;
  image_count: number;
  bead_spec: ApiBeadSpec;
  route_policy: string;
  created_at: string;
  updated_at: string;
  images: ApiImage[];
}

interface ApiStage {
  id: string;
  label: string;
  status: string;
  progress: number;
  message?: string | null;
}

interface ApiJob {
  id: string;
  project_id: string;
  status: string;
  stages: ApiStage[];
  created_at: string;
  updated_at: string;
  error?: string | null;
  error_code?: string | null;
  error_details?: Record<string, unknown>;
}

interface ApiArtifact {
  id: string;
  kind: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  download_url: string;
}

interface ApiVoxelPreviewCell {
  x: number;
  y: number;
  color: string;
  hex: string;
}

interface ApiVoxelPreview {
  project_id: string;
  artifact_id: string;
  grid_shape: [number, number, number];
  grid_extent_mm: [number, number, number];
  pitch_mm: number;
  slice_index: number;
  slice_count: number;
  occupied_count: number;
  color_counts: Record<string, number>;
  palette: Record<string, string>;
  cells: ApiVoxelPreviewCell[];
}

export interface CreateProjectPayload {
  name: string;
  beadSpec: BeadSpec;
}

export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly details: Record<string, unknown> = {}
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
  if (!isFormData && init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { error?: { code?: string; message?: string; details?: Record<string, unknown> } }
      | null;
    throw new ApiError(
      payload?.error?.code ?? "HTTP_ERROR",
      payload?.error?.message ?? response.statusText,
      payload?.error?.details ?? {}
    );
  }

  return (await response.json()) as T;
}

function mapImage(image: ApiImage): ProjectImage {
  return {
    id: image.id,
    filename: image.filename,
    contentType: image.content_type,
    sizeBytes: image.size_bytes,
    sha256: image.sha256,
    view: image.view,
    relativePath: image.relative_path
  };
}

function mapProject(project: ApiProject): Project {
  return {
    id: project.id,
    name: project.name,
    status: project.status as Project["status"],
    imageCount: project.image_count,
    beadSpec: {
      size: project.bead_spec.size,
      outerDiameterMm: project.bead_spec.outer_diameter_mm,
      pitchMm: project.bead_spec.pitch_mm,
      heightMm: project.bead_spec.height_mm,
      holeDiameterMm: project.bead_spec.hole_diameter_mm,
      boardMaxCellsX: project.bead_spec.board_max_cells_x,
      boardMaxCellsY: project.bead_spec.board_max_cells_y
    },
    routePolicy: project.route_policy,
    createdAt: project.created_at,
    updatedAt: project.updated_at,
    images: project.images.map(mapImage)
  };
}

function mapJob(job: ApiJob): Job {
  return {
    id: job.id,
    projectId: job.project_id,
    status: job.status as Job["status"],
    stages: job.stages.map(
      (stage): PipelineStage => ({
        id: stage.id,
        label: stage.label,
        description: stage.message ?? "",
        status: stage.status as PipelineStage["status"],
        progress: stage.progress,
        message: stage.message
      })
    ),
    createdAt: job.created_at,
    updatedAt: job.updated_at,
    error: job.error,
    errorCode: job.error_code,
    errorDetails: job.error_details
  };
}

const artifactTitles: Record<ArtifactKind, string> = {
  model_glb: "Tripo 3D 模型",
  design_json: "设计 JSON",
  layout_svg: "展开网格图",
  layout_png: "展开网格预览",
  exploded_svg: "爆炸装配图",
  three_view_svg: "成品三视图",
  assembly_pdf: "装配说明 PDF",
  bom_csv: "色号 / 颗数清单",
  validation_json: "校验报告"
};

const artifactDescriptions: Record<ArtifactKind, string> = {
  model_glb: "Tripo 多视角重建得到的 GLB 原始模型。",
  design_json: "完整板件、接头、装配 DAG 和体素数据。",
  layout_svg: "逐板坐标、编号、色号图例、每色颗数与孔槽标记。",
  layout_png: "展开网格图的位图预览。",
  exploded_svg: "沿装配轴拉开，带插入箭头与顺序号。",
  three_view_svg: "前 / 上 / 侧视图，核对朝向与层次。",
  assembly_pdf: "A4 1:1 打印，含校验尺、步骤和双面有孔烫法说明。",
  bom_csv: "按色号汇总每板颗数，便于备豆。",
  validation_json: "路线守卫、连通性、DAG 和自锁判据报告。"
};

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function mapArtifact(artifact: ApiArtifact): Artifact {
  const kind = artifact.kind as ArtifactKind;
  return {
    id: artifact.id,
    kind,
    title: artifactTitles[kind] ?? artifact.filename,
    description: artifactDescriptions[kind] ?? "生成产物",
    filename: artifact.filename,
    sizeLabel: formatBytes(artifact.size_bytes),
    status: "ready",
    downloadUrl: artifact.download_url
  };
}

function mapVoxelPreview(preview: ApiVoxelPreview): VoxelPreview {
  return {
    projectId: preview.project_id,
    artifactId: preview.artifact_id,
    gridShape: preview.grid_shape,
    gridExtentMm: preview.grid_extent_mm,
    pitchMm: preview.pitch_mm,
    sliceIndex: preview.slice_index,
    sliceCount: preview.slice_count,
    occupiedCount: preview.occupied_count,
    colorCounts: preview.color_counts,
    palette: preview.palette,
    cells: preview.cells.map(
      (cell): VoxelPreviewCell => ({
        x: cell.x,
        y: cell.y,
        color: cell.color,
        hex: cell.hex
      })
    )
  };
}

export const api = {
  createProject(payload: CreateProjectPayload): Promise<Project> {
    return request<ApiProject>("/projects", {
      method: "POST",
      body: JSON.stringify({
        name: payload.name,
        bead_spec: {
          size: payload.beadSpec.size,
          outer_diameter_mm: payload.beadSpec.outerDiameterMm,
          pitch_mm: payload.beadSpec.pitchMm,
          height_mm: payload.beadSpec.heightMm,
          hole_diameter_mm: payload.beadSpec.holeDiameterMm,
          board_max_cells_x: payload.beadSpec.boardMaxCellsX,
          board_max_cells_y: payload.beadSpec.boardMaxCellsY
        }
      })
    }).then(mapProject);
  },

  getProject(projectId: string): Promise<Project> {
    return request<ApiProject>(`/projects/${projectId}`).then(mapProject);
  },

  uploadImages(projectId: string, files: File[]): Promise<Project> {
    const form = new FormData();
    files.forEach((file) => form.append("files", file, file.name));
    form.append("view", "unknown");
    return request<ApiProject>(`/projects/${projectId}/images`, {
      method: "POST",
      body: form
    }).then(mapProject);
  },

  compileProject(projectId: string): Promise<Job> {
    return request<ApiJob>(`/projects/${projectId}/compile`, {
      method: "POST",
      body: JSON.stringify({
        route_policy: "shape_partitioned_double_sided_hole_glue_free",
        options: {}
      })
    }).then(mapJob);
  },

  getJob(jobId: string): Promise<Job> {
    return request<ApiJob>(`/jobs/${jobId}`).then(mapJob);
  },

  retryJob(jobId: string): Promise<Job> {
    return request<ApiJob>(`/jobs/${jobId}/retry`, {
      method: "POST"
    }).then(mapJob);
  },

  listArtifacts(projectId: string): Promise<Artifact[]> {
    return request<ApiArtifact[]>(`/projects/${projectId}/artifacts`).then((items) =>
      items.map(mapArtifact)
    );
  },

  getVoxelPreview(projectId: string, options: VoxelPreviewOptions = {}): Promise<VoxelPreview> {
    const params = new URLSearchParams();
    if (options.z !== undefined) params.set("z", String(options.z));
    if (options.targetHeightMm !== undefined) {
      params.set("target_height_mm", String(options.targetHeightMm));
    }
    if (options.sourceUpAxis !== undefined) {
      params.set("source_up_axis", options.sourceUpAxis);
    }
    if (options.deltaETolerance !== undefined) {
      params.set("delta_e_tolerance", String(options.deltaETolerance));
    }
    const query = params.toString();
    return request<ApiVoxelPreview>(
      `/projects/${projectId}/voxel-preview${query ? `?${query}` : ""}`
    ).then(mapVoxelPreview);
  }
};
