from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "src/Cartomize.ArcGISPro/Services"
VIEWS = ROOT / "src/Cartomize.ArcGISPro/Views"


class ProjectEngineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.view_model = (VIEWS / "CartomizeDockPaneViewModel.cs").read_text(encoding="utf-8")
        self.xaml = (VIEWS / "CartomizeContentView.xaml").read_text(encoding="utf-8")
        self.recommendation = (SERVICES / "NativeRasterRecommendationService.cs").read_text(encoding="utf-8")
        self.analysis = (SERVICES / "NativeRasterAnalysisService.cs").read_text(encoding="utf-8")

    def test_project_analysis_dispatches_to_the_correct_smart_engine(self):
        automation = self.view_model.split("private async Task AnalyzeAutomationAsync()", 1)[1]
        automation = automation.split("private async Task GenerateSelectedVariantAsync()", 1)[0]
        self.assertIn("AnalyzeRasterRecommendationAsync", automation)
        self.assertIn("AnalyzeVectorRecommendationAsync", automation)
        self.assertIn("selectedLayer is RasterLayer", automation)
        self.assertIn("selectedLayer is BasicFeatureLayer", automation)

    def test_main_apply_reuses_detected_raster_classes_and_nodata(self):
        apply_method = self.view_model.split("private async Task ApplyRecommendationAsync()", 1)[1]
        apply_method = apply_method.split("private async Task RestorePreviousStyleAsync()", 1)[0]
        self.assertIn("NativeRasterRecommendationService.ApplyAsync", apply_method)
        self.assertIn("_lastRasterRecommendation", apply_method)
        self.assertIn("AutomaticNoDataValues", apply_method)
        self.assertIn("NativeRasterOutlineService.ExistsAsync", apply_method)
        self.assertIn("NativeRasterOutlineService.ApplyAsync(layer, false", self.recommendation)

    def test_rectangular_padding_has_a_safe_spatial_rule(self):
        for evidence in (
            "LikelyPaddingValue(value)",
            "frequencies.Count >= 2",
            "cornerPercentage >= 0.94",
            "borderPercentage >= 0.40",
            "cornerPercentage - centerPercentage >= 0.12",
            "Valeur de remplissage rectangulaire",
        ):
            self.assertIn(evidence, self.analysis)

    def test_single_useful_class_remains_categorical_after_padding_is_masked(self):
        catalog = (SERVICES / "NativeRasterNomenclatureService.cs").read_text(encoding="utf-8")
        self.assertIn("observedUnique >= 2 || automaticNoData.Count > 0", self.analysis)
        self.assertIn("SingleClassNomenclature", catalog)
        self.assertIn('"Présence forestière", "Forêt"', catalog)

    def test_detected_classes_and_color_swatches_are_visible_in_project_tab(self):
        ET.parse(VIEWS / "CartomizeContentView.xaml")
        self.assertIn('ItemsSource="{Binding RasterRecommendationClasses}"', self.xaml)
        self.assertIn('Background="{Binding ColorBrush}"', self.xaml)
        self.assertIn('Header="Classe"', self.xaml)
        self.assertIn('Header="État"', self.xaml)

    def test_vector_apply_is_multi_layer_and_reversible(self):
        self.assertIn("NativeVectorWorkspaceService.ApplyCompositionAsync", self.view_model)
        self.assertIn("NativeVectorWorkspaceService.CaptureCompositionAsync", self.view_model)
        self.assertIn("NativeVectorWorkspaceService.RestoreCompositionAsync", self.view_model)


if __name__ == "__main__":
    unittest.main()
