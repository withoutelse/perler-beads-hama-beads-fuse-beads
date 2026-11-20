import type { BeadSize } from "../types/domain";

const options: Array<{
  value: BeadSize;
  title: string;
  subtitle: string;
  detail: string;
  badge: string;
}> = [
  {
    value: "5mm",
    title: "5mm 标准豆",
    subtitle: "Midi",
    detail: "外径 5.0 mm · 孔径 2.2 mm · 29×29 板",
    badge: "通用"
  },
  {
    value: "2.6mm",
    title: "2.6mm 迷你豆",
    subtitle: "Mini",
    detail: "外径 2.6 mm · 孔径约 1.0 mm · 57×57 板",
    badge: "高精度"
  }
];

export function BeadSpecPicker({
  value,
  onChange
}: {
  value: BeadSize;
  onChange: (value: BeadSize) => void;
}) {
  return (
    <div className="spec-grid">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={`spec-card ${value === option.value ? "spec-card--active" : ""}`}
          onClick={() => onChange(option.value)}
        >
          <div className="spec-card-top">
            <span className="spec-card-title">{option.title}</span>
            <span className="spec-badge">{option.badge}</span>
          </div>
          <span className="spec-card-subtitle">{option.subtitle}</span>
          <span className="spec-card-detail">{option.detail}</span>
        </button>
      ))}
    </div>
  );
}
