from __future__ import annotations

from dataclasses import dataclass
from heapq import heapify, heappop, heappush


@dataclass(frozen=True, slots=True)
class AssemblyEdge:
    before: str
    after: str
    joint_id: str | None = None

    def __post_init__(self) -> None:
        if not self.before or not self.after:
            raise ValueError("assembly edge endpoints are required")
        if self.before == self.after:
            raise ValueError("assembly self edges are not allowed")


@dataclass(frozen=True, slots=True)
class AssemblyGraph:
    nodes: frozenset[str]
    edges: tuple[AssemblyEdge, ...] = ()

    def __post_init__(self) -> None:
        if not self.nodes:
            raise ValueError("assembly graph must contain nodes")
        for edge in self.edges:
            if edge.before not in self.nodes or edge.after not in self.nodes:
                raise ValueError("assembly edge references an unknown node")

    def topological_order(self) -> tuple[str, ...] | None:
        indegree = {node: 0 for node in self.nodes}
        outgoing: dict[str, list[str]] = {node: [] for node in self.nodes}
        for edge in self.edges:
            indegree[edge.after] += 1
            outgoing[edge.before].append(edge.after)

        ready = [node for node, degree in indegree.items() if degree == 0]
        heapify(ready)
        order: list[str] = []
        while ready:
            node = heappop(ready)
            order.append(node)
            for neighbor in outgoing[node]:
                indegree[neighbor] -= 1
                if indegree[neighbor] == 0:
                    heappush(ready, neighbor)
        return tuple(order) if len(order) == len(self.nodes) else None

    def has_cycle(self) -> bool:
        return self.topological_order() is None

    def sinks(self) -> tuple[str, ...]:
        has_outgoing = {edge.before for edge in self.edges}
        return tuple(sorted(node for node in self.nodes if node not in has_outgoing))

    def unique_sink(self) -> str | None:
        sinks = self.sinks()
        return sinks[0] if len(sinks) == 1 else None
