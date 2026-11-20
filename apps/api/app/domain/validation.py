from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import pairwise

from app.domain.design import Design
from app.domain.plate import PlateKind
from app.domain.route import RouteGuard


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str
    severity: Severity = Severity.ERROR
    plate_id: str | None = None
    joint_id: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not any(issue.severity is Severity.ERROR for issue in self.issues)

    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is Severity.ERROR)

    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is Severity.WARNING)

    def raise_for_errors(self) -> None:
        if not self.ok:
            raise ValueError("; ".join(issue.message for issue in self.errors()))


class DesignValidator:
    def __init__(self, route_guard: RouteGuard | None = None) -> None:
        self._route_guard = route_guard or RouteGuard()

    def validate(self, design: Design) -> ValidationReport:
        issues: list[ValidationIssue] = []

        route_check = self._route_guard.check(design.route_features)
        for feature in route_check.missing:
            issues.append(
                ValidationIssue(
                    code="ROUTE_REQUIRED_FEATURE_MISSING",
                    message=f"缺少必需路线特征：{feature.value}",
                )
            )
        for feature in route_check.forbidden:
            issues.append(
                ValidationIssue(
                    code="ROUTE_FORBIDDEN_FEATURE",
                    message=f"出现禁止路线特征：{feature.value}",
                )
            )

        if not design.voxel_grid.occupied:
            issues.append(
                ValidationIssue(
                    code="VOXELIZATION_EMPTY",
                    message="体素网格为空，无法生成板件",
                )
            )

        plate_ids = [plate.id for plate in design.plates]
        if len(plate_ids) != len(set(plate_ids)):
            issues.append(ValidationIssue("PLATE_ID_DUPLICATE", "板件 ID 必须唯一"))
        plate_by_id = {plate.id: plate for plate in design.plates}

        for plate in design.plates:
            if not plate.is_4_connected():
                issues.append(
                    ValidationIssue(
                        code="PLATE_DISCONNECTED",
                        message=f"{plate.id} 不是 4-连通板件",
                        plate_id=plate.id,
                    )
                )
            if (
                plate.width() > design.bead_spec.board_max_cells_x
                or plate.height() > design.bead_spec.board_max_cells_y
            ):
                issues.append(
                    ValidationIssue(
                        code="PLATE_OVERSIZE",
                        message=f"{plate.id} 超过单板最大格数",
                        plate_id=plate.id,
                    )
                )
            for color_id in set(plate.color_by_cell.values()):
                if color_id not in design.palette:
                    issues.append(
                        ValidationIssue(
                            code="COLOR_NOT_IN_PALETTE",
                            message=f"{plate.id} 使用了未登记色号 {color_id}",
                            plate_id=plate.id,
                        )
                    )

        for joint in design.joints:
            if joint.plate_a not in plate_by_id or joint.plate_b not in plate_by_id:
                issues.append(
                    ValidationIssue(
                        code="JOINT_ORPHAN",
                        message=f"{joint.id} 引用了不存在的板件",
                        joint_id=joint.id,
                    )
                )
                continue
            if not joint.tongue_cells <= joint.slot_cells:
                issues.append(
                    ValidationIssue(
                        code="JOINT_NOT_COMPLEMENTARY",
                        message=f"{joint.id} 的舌未完全落在槽内",
                        joint_id=joint.id,
                    )
                )

        groups: dict[tuple[str, str], list] = {}
        for joint in design.joints:
            groups.setdefault((joint.plate_a, joint.edge_a), []).append(joint)
        for (plate_id, edge), joints in groups.items():
            if len(joints) < 2:
                continue
            ordered = sorted(joints, key=lambda item: item.position)
            for left, right in pairwise(ordered):
                required_gap = max(left.width, right.width) + 2
                if right.position - left.position < required_gap:
                    issues.append(
                        ValidationIssue(
                            code="JOINT_SPACING_VIOLATION",
                            message=f"{plate_id} 的 {edge} 边上 {left.id}/{right.id} 间距不足",
                            plate_id=plate_id,
                            joint_id=right.id,
                        )
                    )

        if set(design.assembly.nodes) != set(plate_ids):
            issues.append(
                ValidationIssue(
                    code="ASSEMBLY_NODE_MISMATCH",
                    message="装配图节点必须与板件集合一致",
                )
            )
        if design.assembly.has_cycle():
            issues.append(ValidationIssue("ASSEMBLY_CYCLE", "装配图存在环"))
        if design.assembly.unique_sink() is None:
            issues.append(
                ValidationIssue(
                    code="ASSEMBLY_NO_UNIQUE_SINK",
                    message="装配图必须存在唯一汇点",
                )
            )

        if design.bottom_ring_id is None:
            issues.append(
                ValidationIssue(
                    code="BOTTOM_RING_MISSING",
                    message="未指定底环，无法验证无胶自锁",
                    severity=Severity.WARNING,
                )
            )
        else:
            bottom_ring = plate_by_id.get(design.bottom_ring_id)
            if bottom_ring is None:
                issues.append(
                    ValidationIssue(
                        code="BOTTOM_RING_MISSING",
                        message="底环 ID 不存在",
                        plate_id=design.bottom_ring_id,
                    )
                )
            elif bottom_ring.kind is not PlateKind.RING:
                issues.append(
                    ValidationIssue(
                        code="BOTTOM_RING_KIND_INVALID",
                        message="底环必须是 RING 板件",
                        plate_id=bottom_ring.id,
                    )
                )

        return ValidationReport(tuple(issues))
