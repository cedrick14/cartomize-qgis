from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "src/Cartomize.ArcGISPro/Services"
VIEWS = ROOT / "src/Cartomize.ArcGISPro/Views"


class NativeAutomationLayoutTests(unittest.TestCase):
    def setUp(self):
        self.view_model = (VIEWS / "CartomizeDockPaneViewModel.cs").read_text(encoding="utf-8")
        self.layout = (SERVICES / "NativeLayoutService.cs").read_text(encoding="utf-8")
        self.selector = (SERVICES / "NativeTemplateRecommendationService.cs").read_text(encoding="utf-8")

    def test_template_choice_uses_engine_analysis(self):
        for signal in (
            "RasterTheme",
            "RasterType",
            "PrimaryVectorRole",
            "ClassCount",
            "RelationCount",
            'template.Category == "occupation_sol"',
            'template.Category == "environnement"',
            "template.MapFrameCount >= 3",
        ):
            self.assertIn(signal, self.selector)
        self.assertIn("NativeTemplateRecommendationService.Recommend", self.view_model)
        self.assertIn("raster?.Sample.Theme", self.view_model)
        self.assertIn("vector?.Relations.Count", self.view_model)

    def test_selected_proposal_always_applies_recommendation_before_layout(self):
        start = self.view_model.index("private async Task<bool> ExecuteAutopilotAsync")
        end = self.view_model.index("private void SaveRecipe", start)
        method = self.view_model[start:end]
        self.assertNotIn("AutomationApplySymbology &&", method)
        self.assertLess(method.index("await ApplyRecommendationAsync()"), method.index('await ExecuteLayoutAsync("Créer"'))

    def test_raster_layout_receives_exact_classes_and_colors(self):
        self.assertIn("CurrentRasterLegendClasses()", self.view_model)
        self.assertIn("new NativeLayoutLegendClass(item.Label, item.Color)", self.view_model)
        for signal in (
            "NativeLayoutLegendClass",
            "CreateClassLegend",
            "legend-swatch-",
            "legend-class-",
            "request.LegendClasses is { Count: > 0 }",
        ):
            self.assertIn(signal, self.layout)
        self.assertNotIn("ZONE DE GRAPHIQUE", self.layout)
        self.assertNotIn("ZONE DE TABLEAU", self.layout)

    def test_automatic_raster_outline_is_disabled_but_manual_option_remains(self):
        window = (VIEWS / "RasterEngineWindow.xaml.cs").read_text(encoding="utf-8")
        xaml_path = VIEWS / "RasterEngineWindow.xaml"
        ET.parse(xaml_path)
        xaml = xaml_path.read_text(encoding="utf-8")
        self.assertIn("private bool _addBlackOutline;", window)
        self.assertNotIn("private bool _addBlackOutline = true;", window)
        self.assertIn("{Binding AddBlackOutline}", xaml)

    def test_automation_ui_explains_the_complete_action(self):
        xaml_path = VIEWS / "CartomizeContentView.xaml"
        ET.parse(xaml_path)
        text = xaml_path.read_text(encoding="utf-8")
        self.assertIn("applique automatiquement la symbologie recommandée", text)
        self.assertIn("actualise la légende", text)
        self.assertNotIn("Harmoniser la symbologie du projet", text)


if __name__ == "__main__":
    unittest.main()
