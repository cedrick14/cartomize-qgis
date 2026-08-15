from __future__ import annotations

import ast
from pathlib import Path
import unittest

from cartomize_qgis.core.layer_stack import LayerDescriptor, plan_layer_stacks
from cartomize_qgis.core.legend_safety import isolate_legend_model


class _FakeLegend:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.auto_update = True
        self.calls: list[bool] = []

    def setAutoUpdateModel(self, enabled: bool) -> None:
        self.calls.append(enabled)
        if self.fail:
            raise RuntimeError("simulated QGIS failure")
        self.auto_update = enabled

    def autoUpdateModel(self) -> bool:
        return self.auto_update


class LegendIsolationTests(unittest.TestCase):
    def test_legend_is_detached_before_customization(self):
        legend = _FakeLegend()

        self.assertTrue(isolate_legend_model(legend))
        self.assertFalse(legend.auto_update)
        self.assertEqual(legend.calls, [False])

    def test_failed_detachment_is_reported_as_unsafe(self):
        legend = _FakeLegend(fail=True)

        self.assertFalse(isolate_legend_model(legend))
        self.assertEqual(legend.calls, [False])

    def test_layout_builder_isolates_before_touching_legend_tree(self):
        source_path = (
            Path(__file__).resolve().parents[1] / "core" / "layout_builder.py"
        )
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        builder = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "LayoutBuilder"
        )
        cleaner = next(
            node
            for node in builder.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_clean_legend_model"
        )

        isolate_lines = []
        model_lines = []
        removal_lines = []
        for node in ast.walk(cleaner):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == "isolate_legend_model":
                isolate_lines.append(node.lineno)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "model":
                model_lines.append(node.lineno)
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "removeChildNode"
            ):
                removal_lines.append(node.lineno)

        self.assertTrue(isolate_lines)
        self.assertTrue(model_lines)
        self.assertTrue(removal_lines)
        self.assertLess(min(isolate_lines), min(model_lines))
        self.assertLess(min(model_lines), min(removal_lines))


class ContextStackTests(unittest.TestCase):
    def setUp(self):
        self.layers = (
            LayerDescriptor("thematic", "vector"),
            LayerDescriptor("roads", "vector"),
            LayerDescriptor("osm", "raster", basemap=True),
        )

    def test_selected_basemap_stays_at_bottom_of_main_map(self):
        plan = plan_layer_stacks(
            self.layers,
            selected_ids=("thematic", "roads", "osm"),
            visible_ids=("thematic", "roads", "osm"),
            focus_id="thematic",
            background_mode="layer",
            background_layer_id="osm",
        )

        self.assertEqual(plan.main_ids, ("thematic", "roads", "osm"))
        self.assertEqual(plan.background_ids, ("osm",))
        self.assertIn("osm", plan.locator_ids)

    def test_automatic_basemap_is_not_lost_after_analysis_selection(self):
        plan = plan_layer_stacks(
            self.layers,
            selected_ids=("thematic",),
            visible_ids=("thematic", "roads", "osm"),
            focus_id="thematic",
            include_visible_context=True,
            background_mode="automatic",
        )

        self.assertEqual(plan.main_ids, ("thematic", "roads", "osm"))
        self.assertEqual(plan.background_ids, ("osm",))

    def test_thematic_only_mode_excludes_basemap_without_deleting_it(self):
        plan = plan_layer_stacks(
            self.layers,
            visible_ids=("thematic", "roads", "osm"),
            background_mode="none",
        )

        self.assertEqual(plan.main_ids, ("thematic", "roads"))
        self.assertEqual(plan.background_ids, ())


if __name__ == "__main__":
    unittest.main()
