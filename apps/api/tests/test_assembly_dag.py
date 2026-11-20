import unittest

from app.domain.assembly import AssemblyEdge, AssemblyGraph


class AssemblyGraphTests(unittest.TestCase):
    def test_topological_order(self) -> None:
        graph = AssemblyGraph(
            nodes=frozenset({"ring", "wall", "cap"}),
            edges=(
                AssemblyEdge("ring", "wall"),
                AssemblyEdge("wall", "cap"),
            ),
        )
        self.assertEqual(graph.topological_order(), ("ring", "wall", "cap"))
        self.assertFalse(graph.has_cycle())
        self.assertEqual(graph.unique_sink(), "cap")

    def test_cycle_is_detected(self) -> None:
        graph = AssemblyGraph(
            nodes=frozenset({"a", "b"}),
            edges=(AssemblyEdge("a", "b"), AssemblyEdge("b", "a")),
        )
        self.assertTrue(graph.has_cycle())
        self.assertIsNone(graph.unique_sink())

    def test_multiple_sinks_are_not_unique(self) -> None:
        graph = AssemblyGraph(
            nodes=frozenset({"a", "b", "c"}),
            edges=(AssemblyEdge("a", "b"),),
        )
        self.assertEqual(graph.sinks(), ("b", "c"))
        self.assertIsNone(graph.unique_sink())


if __name__ == "__main__":
    unittest.main()
