import type {
  Artifact,
  BeadSpec,
  PipelineStage,
  PlateKind,
  PlateSummary,
  Project,
  ValidationIssue
} from "../types/domain";

type Cell = [number, number];

const ORANGE = "#e86f2d";
const CREAM = "#f6d7b8";
const WHITE = "#fffaf2";
const DARK = "#5b3a29";

function makeColorMap(cells: Cell[], colors: string[]): Record<string, string> {
  return Object.fromEntries(
    cells.map(([x, y], index) => [`${x},${y}`, colors[index % colors.length]])
  );
}

function makeColorCounts(cells: Cell[], colors: string[]): Record<string, number> {
  const counts: Record<string, number> = {};
  cells.forEach((_cell, index) => {
    const color = colors[index % colors.length];
    counts[color] = (counts[color] ?? 0) + 1;
  });
  return counts;
}

function ringCells(size: number, holeStart: number, holeEnd: number): Cell[] {
  const cells: Cell[] = [];
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const inHole = x >= holeStart && x <= holeEnd && y >= holeStart && y <= holeEnd;
      if (!inHole) cells.push([x, y]);
    }
  }
  return cells;
}

function crossCells(size: number): Cell[] {
  const cells: Cell[] = [];
  const mid = Math.floor(size / 2);
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      if (Math.abs(x - mid) <= 1 || Math.abs(y - mid) <= 1) cells.push([x, y]);
    }
  }
  return cells;
}

function rectangleCells(width: number, height: number): Cell[] {
  const cells: Cell[] = [];
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) cells.push([x, y]);
  }
  return cells;
}

function makePlate(
  id: string,
  kind: PlateKind,
  label: string,
  width: number,
  height: number,
  cells: Cell[],
  colors: string[]
): PlateSummary {
  return {
    id,
    kind,
    label,
    width,
    height,
    cellCount: cells.length,
    colorCounts: makeColorCounts(cells, colors),
    cells,
    colorByCell: makeColorMap(cells, colors)
  };
}

export const demoBeadSpec: BeadSpec = {
  size: "5mm",
  outerDiameterMm: 5,
  pitchMm: 5,
  heightMm: 5.1,
  holeDiameterMm: 2.2,
  boardMaxCellsX: 29,
  boardMaxCellsY: 29
};

export const demoProject: Project = {
  id: "prj_demo_001",
  name: "橙色小圆罐 · 3D 拼豆",
  status: "ready",
  imageCount: 8,
  beadSpec: demoBeadSpec,
  routePolicy: "shape_partitioned_double_sided_hole_glue_free",
  createdAt: "2026-11-19T10:00:00+08:00",
  updatedAt: "2026-11-19T10:42:00+08:00",
  images: []
};

export const demoStages: PipelineStage[] = [
  {
    id: "ingest",
    label: "输入校验",
    description: "8 张多视角图片，视角覆盖 front / back / left / right / top",
    status: "succeeded",
    progress: 100
  },
  {
    id: "reconstruct",
    label: "3D 重建",
    description: "Tripo 重建完成，模型归一化到 5mm 体素",
    status: "succeeded",
    progress: 100
  },
  {
    id: "voxelize",
    label: "实心体素化",
    description: "内部填充完成，识别 4 个颜色簇",
    status: "succeeded",
    progress: 100
  },
  {
    id: "decompose",
    label: "层带 / 板件分解",
    description: "检测到 3 个层带，正在生成环片与围板",
    status: "running",
    progress: 68
  },
  {
    id: "joints",
    label: "卡扣合成",
    description: "互补舌槽、双面有孔烫法、装配 DAG",
    status: "pending",
    progress: 0
  },
  {
    id: "layout",
    label: "2D 排版",
    description: "板件展开、色号图例、BOM",
    status: "pending",
    progress: 0
  },
  {
    id: "render",
    label: "图形渲染",
    description: "展开网格图、爆炸图、三视图",
    status: "pending",
    progress: 0
  },
  {
    id: "export",
    label: "PDF / BOM 导出",
    description: "可打印装配说明",
    status: "pending",
    progress: 0
  },
  {
    id: "validate",
    label: "门禁校验",
    description: "路线守卫、连通性、DAG、自锁判据",
    status: "pending",
    progress: 0
  }
];

export const demoPlates: PlateSummary[] = [
  makePlate("P01", "ring", "底环 · 橙色", 7, 7, ringCells(7, 2, 4), [ORANGE, CREAM]),
  makePlate("P02", "perimeter", "围板 · 4 段直片", 9, 4, rectangleCells(9, 4), [ORANGE, WHITE, CREAM]),
  makePlate("P03", "cross_skeleton", "中心十字骨架", 7, 7, crossCells(7), [WHITE, CREAM]),
  makePlate("P04", "cap", "封顶环片", 5, 5, ringCells(5, 1, 3), [ORANGE, DARK])
];

export const demoValidation: ValidationIssue[] = [
  {
    code: "ROUTE_GUARD_PASSED",
    severity: "warning",
    message: "路线守卫通过：按造型分件 + 双面有孔 + 免胶拼插。"
  },
  {
    code: "PLATE_CONNECTED",
    severity: "warning",
    message: "4 个板件均为 4-连通，无碎孤岛。"
  },
  {
    code: "ASSEMBLY_UNIQUE_SINK",
    severity: "warning",
    message: "装配 DAG 唯一汇点为 P04，封顶方向 z-。"
  },
  {
    code: "JOINT_EDGE_CLEARANCE",
    severity: "warning",
    message: "P03 的槽口靠近边缘，建议内移 1 格以降低撕裂风险。"
  }
];

export const demoArtifacts: Artifact[] = [
  {
    id: "art_layout_svg",
    kind: "layout_svg",
    title: "展开网格图",
    description: "逐板坐标、编号、色号图例、每色颗数与孔槽标记。",
    filename: "layout.svg",
    sizeLabel: "48 KB",
    status: "ready"
  },
  {
    id: "art_exploded_svg",
    kind: "exploded_svg",
    title: "爆炸装配图",
    description: "沿装配轴拉开，带插入箭头与顺序号。",
    filename: "exploded.svg",
    sizeLabel: "36 KB",
    status: "ready"
  },
  {
    id: "art_three_view_svg",
    kind: "three_view_svg",
    title: "成品三视图",
    description: "前 / 上 / 侧视图，核对朝向与层次。",
    filename: "three-view.svg",
    sizeLabel: "待生成",
    status: "pending"
  },
  {
    id: "art_assembly_pdf",
    kind: "assembly_pdf",
    title: "装配说明 PDF",
    description: "A4 1:1 打印，含校验尺、步骤和双面有孔烫法说明。",
    filename: "assembly.pdf",
    sizeLabel: "待生成",
    status: "pending"
  },
  {
    id: "art_bom_csv",
    kind: "bom_csv",
    title: "色号 / 颗数清单",
    description: "按色号汇总每板颗数，便于备豆。",
    filename: "bom.csv",
    sizeLabel: "6 KB",
    status: "ready"
  },
  {
    id: "art_design_json",
    kind: "design_json",
    title: "设计 JSON",
    description: "完整板件、接头、装配 DAG 和体素数据。",
    filename: "design.json",
    sizeLabel: "1.2 MB",
    status: "ready"
  }
];
