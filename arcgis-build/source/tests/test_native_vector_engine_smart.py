from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "src/Cartomize.ArcGISPro/Services"
VIEWS = ROOT / "src/Cartomize.ArcGISPro/Views"


class NativeVectorEngineSmartTests(unittest.TestCase):
    def setUp(self):
        self.service = (SERVICES / "NativeVectorWorkspaceService.cs").read_text(encoding="utf-8")
        self.window = (VIEWS / "VectorEngineWindow.xaml.cs").read_text(encoding="utf-8")
        self.xaml = (VIEWS / "VectorEngineWindow.xaml").read_text(encoding="utf-8")
        self.view_model = (VIEWS / "CartomizeDockPaneViewModel.cs").read_text(encoding="utf-8")
        self.style = (SERVICES / "NativeStyleService.cs").read_text(encoding="utf-8")

    def test_multi_layer_inventory_and_profiles_reuse_native_engine(self):
        self.assertIn("MaximumAnalyzedLayers = 32", self.service)
        self.assertIn("AnalyzeVectorOnWorker", self.service)
        self.assertIn("requestedLayerIds", self.service)
        self.assertIn("IReadOnlyList<NativeLayerProfile> Profiles", self.service)
        self.assertIn("IsIncluded", self.window)

    def test_spatial_relations_use_native_arcgis_queries(self):
        self.assertIn("SpatialQueryFilter", self.service)
        self.assertIn("SpatialRelationship.Intersects", self.service)
        self.assertIn("CountSpatialIntersections", self.service)
        self.assertIn("ExtentOverlapPercent", self.service)
        self.assertNotIn("ArcGIS.Desktop.Core.Geoprocessing", self.service)

    def test_relation_rules_cover_core_overlay_cases(self):
        for text in (
            "Jointure spatiale et agrégation",
            "Intersection par paire",
            "Surfaces et pourcentages de recouvrement",
            "Plus proche / agrégation spatiale",
            "Croisement de réseaux",
        ):
            self.assertIn(text, self.service)

    def test_composition_is_reversible_and_role_aware(self):
        self.assertIn("CaptureCompositionAsync", self.service)
        self.assertIn("RestoreCompositionAsync", self.service)
        self.assertIn("map.MoveLayer", self.service)
        self.assertIn("ApplyVectorProfileOnWorker", self.service)
        for role in ("transport", "hydrographie", "limites", "localités", "occupation_sol"):
            self.assertIn(f'"{role}"', self.style)
        self.assertIn("_snapshot", self.window)

    def test_vector_engine_ui_is_complete_and_well_formed(self):
        ET.parse(VIEWS / "VectorEngineWindow.xaml")
        for tab in ("Couches", "Relations spatiales", "Composition", "Plan d’automatisation"):
            self.assertIn(f'Header="{tab}"', self.xaml)
        for binding in (
            "Layers", "PrimaryLayer", "Relations", "Composition",
            "ReorderLayers", "HarmonizeStyles", "EnableSmartLabels",
        ):
            self.assertIn(f"{{Binding {binding}", self.xaml)

    def test_main_panel_opens_the_vector_engine(self):
        self.assertIn("OpenVectorEngineAsync", self.view_model)
        self.assertIn("new VectorEngineWindow", self.view_model)
        content = (VIEWS / "CartomizeContentView.xaml").read_text(encoding="utf-8")
        self.assertIn('Text="Ouvrir Vector Engine multi-couches"', content)
        self.assertIn('Click="OpenVectorEngineClick"', content)


if __name__ == "__main__":
    unittest.main()
