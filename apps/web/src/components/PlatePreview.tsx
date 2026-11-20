import type { PlateSummary } from "../types/domain";

export function PlatePreview({ plate }: { plate: PlateSummary }) {
  const cellSet = new Set(plate.cells.map(([x, y]) => `${x},${y}`));
  const cells = Array.from({ length: plate.width * plate.height }, (_, index) => {
    const x = index % plate.width;
    const y = Math.floor(index / plate.width);
    const key = `${x},${y}`;
    const color = plate.colorByCell[key];
    return (
      <span
        key={key}
        className={`bead-cell ${cellSet.has(key) ? "bead-cell--solid" : "bead-cell--empty"}`}
        style={color ? { backgroundColor: color } : undefined}
      />
    );
  });

  return (
    <div
      className="plate-preview"
      style={{ gridTemplateColumns: `repeat(${plate.width}, 18px)` }}
      aria-label={`${plate.id} ${plate.label} 预览`}
    >
      {cells}
    </div>
  );
}
