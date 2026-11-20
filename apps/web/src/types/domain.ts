export type BeadSize = "5mm" | "2.6mm";
export type ProjectStatus = "draft" | "queued" | "running" | "ready" | "failed";
export type StageStatus = "pending" | "queued" | "running" | "succeeded" | "failed";
export type PlateKind =
  | "ring"
  | "perimeter"
  | "cross_skeleton"
  | "pin_patch"
  | "cap"
  | "splice";
export type ArtifactKind =
  | "model_glb"
  | "design_json"
  | "layout_svg"
  | "layout_png"
  | "exploded_svg"
  | "three_view_svg"
  | "assembly_pdf"
  | "bom_csv"
  | "validation_json";
export type ViewId = "project" | "pipeline" | "design" | "export";

export interface BeadSpec {
  size: BeadSize;
  outerDiameterMm: number;
  pitchMm: number;
  heightMm: number;
  holeDiameterMm: number;
  boardMaxCellsX: number;
  boardMaxCellsY: number;
}

export interface ProjectImage {
  id: string;
  filename: string;
  contentType: string;
  sizeBytes: number;
  sha256: string;
  view: string;
  relativePath: string;
}

export interface Project {
  id: string;
  name: string;
  status: ProjectStatus;
  imageCount: number;
  beadSpec: BeadSpec;
  routePolicy: string;
  createdAt: string;
  updatedAt: string;
  images: ProjectImage[];
}

export interface PipelineStage {
  id: string;
  label: string;
  description: string;
  status: StageStatus;
  progress: number;
  message?: string | null;
}

export interface Job {
  id: string;
  projectId: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  stages: PipelineStage[];
  createdAt: string;
  updatedAt: string;
  error?: string | null;
  errorCode?: string | null;
  errorDetails?: Record<string, unknown>;
}

export interface PlateSummary {
  id: string;
  kind: PlateKind;
  label: string;
  width: number;
  height: number;
  cellCount: number;
  colorCounts: Record<string, number>;
  cells: [number, number][];
  colorByCell: Record<string, string>;
}

export interface ValidationIssue {
  code: string;
  severity: "error" | "warning";
  message: string;
}

export interface VoxelPreviewCell {
  x: number;
  y: number;
  color: string;
  hex: string;
}

export interface VoxelPreview {
  projectId: string;
  artifactId: string;
  gridShape: [number, number, number];
  gridExtentMm: [number, number, number];
  pitchMm: number;
  sliceIndex: number;
  sliceCount: number;
  occupiedCount: number;
  colorCounts: Record<string, number>;
  palette: Record<string, string>;
  cells: VoxelPreviewCell[];
}

export interface VoxelPreviewOptions {
  z?: number;
  targetHeightMm?: number;
  sourceUpAxis?: "y" | "z";
  deltaETolerance?: number;
}

export interface Artifact {
  id: string;
  kind: ArtifactKind;
  title: string;
  description: string;
  filename: string;
  sizeLabel: string;
  status: "ready" | "pending";
  downloadUrl?: string;
}
