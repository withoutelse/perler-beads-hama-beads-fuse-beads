import unittest

from app.domain.route import (
    REQUIRED_ROUTE_FEATURES,
    RouteFeature,
    RouteGuard,
    RouteViolation,
)


class RouteGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = RouteGuard()

    def test_required_route_passes(self) -> None:
        check = self.guard.check(REQUIRED_ROUTE_FEATURES)
        self.assertTrue(check.ok)
        self.assertEqual(check.missing, ())
        self.assertEqual(check.forbidden, ())

    def test_glue_is_rejected(self) -> None:
        check = self.guard.check(REQUIRED_ROUTE_FEATURES | {RouteFeature.GLUE})
        self.assertFalse(check.ok)
        self.assertEqual(check.forbidden, (RouteFeature.GLUE,))

    def test_missing_required_feature_is_reported(self) -> None:
        check = self.guard.check({RouteFeature.SHAPE_PARTITIONED})
        self.assertIn(RouteFeature.DOUBLE_SIDED_HOLE, check.missing)
        self.assertIn(RouteFeature.GLUE_FREE_INTERLOCK, check.missing)

    def test_assert_compliant_raises_with_actionable_message(self) -> None:
        with self.assertRaises(RouteViolation) as context:
            self.guard.assert_compliant(
                REQUIRED_ROUTE_FEATURES | {RouteFeature.CONNECTOR_ROD}
            )
        self.assertIn("connector_rod", str(context.exception))


if __name__ == "__main__":
    unittest.main()
