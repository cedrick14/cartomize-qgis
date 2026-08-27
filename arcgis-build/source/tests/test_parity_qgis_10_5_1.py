from __future__ import annotations

from pathlib import Path
import importlib
import json
import re
import sys
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
XAML = ROOT / "src/Cartomize.ArcGISPro/Views/CartomizeDockPaneView.xaml"
VIEW_MODEL = ROOT / "src/Cartomize.ArcGISPro/Views/CartomizeDockPaneViewModel.cs"
TOOLBOX = ROOT / "toolbox/Cartomize.pyt"
PUBLIC_API = ROOT / "tests/qgis_public_api_10_5_1.json"
NS = "{http://schemas.microsoft.com/winfx/2006/xaml/presentation}"


QGIS_CORE_MODULES = {
    "autopilot.py", "band_semantics.py", "batch.py", "community.py", "community_catalog.py", "compat.py", "constants.py",
    "diagnostics.py", "errors.py", "exporter.py", "extent_policy.py", "geo_intelligence.py", "human_validation.py",
    "label_intelligence.py", "layer_stack.py", "layout_builder.py", "layout_intelligence.py", "layout_plan.py", "legend_safety.py",
    "local_memory.py", "mapops.py", "onboarding_state.py", "preview.py", "project_graph.py", "project_service.py", "project_styling.py",
    "quality.py", "raster_intelligence.py", "raster_intelligence_core.py", "raster_sampling.py", "raster_symbology.py", "raster_themes.py",
    "scale_intelligence.py", "settings.py", "symbology.py", "template_catalog.py", "vector_intelligence.py",
}

EXPECTED_TABS = ["Automatisation", "Projet", "Mise en page", "Qualité", "Production", "Communauté", "Système"]
EXPECTED_BUTTONS = [
    "Analyser le projet", "Créer la proposition sélectionnée", "Créer les trois propositions", "Enregistrer la recette", "Rejouer une recette",
    "Importer des données…", "Afficher l’emprise", "Ouvrir les propriétés", "Analyser la couche sélectionnée", "Appliquer la recommandation",
    "Restaurer le style précédent", "Ouvrir Raster Engine", "Créer la mise en page", "Actualiser la mise en page",
    "Ouvrir l’aperçu HD dans ArcGIS Pro", "Actualiser l’aperçu HD", "Améliorer la lisibilité", "Exporter en PDF", "Exporter en SVG",
    "Exporter en PNG", "Enregistrer en PAGX", "Lancer le contrôle de la qualité", "Vérifier le placement des étiquettes", "Copier le rapport",
    "Parcourir", "Créer un manifeste", "Exécuter la série", "Créer l’état de référence", "Vérifier les changements", "Accepter l’état actuel",
    "Régénérer la dernière recette", "Approuver la mise en page", "Exporter le certificat", "Actualiser le catalogue en ligne",
    "Ouvrir la ressource sélectionnée", "Ouvrir le portail Cartomize", "Actualiser l’état du système",
]


class QgisParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ET.parse(XAML).getroot()
        cls.xaml_text = XAML.read_text(encoding="utf-8")
        cls.view_model = VIEW_MODEL.read_text(encoding="utf-8")
        cls.toolbox = TOOLBOX.read_text(encoding="utf-8")

    def test_all_qgis_core_modules_have_arcgis_counterparts(self):
        current = {path.name for path in (ROOT / "toolbox/cartomize_core").glob("*.py")}
        self.assertEqual(QGIS_CORE_MODULES - current, set())

    def test_all_qgis_public_symbols_are_exported_and_importable(self):
        expected = json.loads(PUBLIC_API.read_text(encoding="utf-8"))
        sys.path.insert(0, str(ROOT / "toolbox"))
        try:
            for module_name, symbols in expected.items():
                module = importlib.import_module(f"cartomize_core.{module_name}")
                missing = [symbol for symbol in symbols if not hasattr(module, symbol)]
                self.assertEqual(missing, [], f"API publique manquante dans {module_name}")
        finally:
            sys.path.pop(0)

    def test_tab_order_is_identical(self):
        self.assertEqual([item.attrib.get("Header") for item in self.root.iter(NS + "TabItem")], EXPECTED_TABS)

    def test_button_labels_and_order_are_identical(self):
        buttons = list(self.root.iter(NS + "Button"))
        self.assertEqual([item.attrib.get("Content") for item in buttons], EXPECTED_BUTTONS)
        self.assertTrue(all("Command" in item.attrib for item in buttons))

    def test_each_button_uses_a_real_view_model_command(self):
        commands = re.findall(r'Command="\{Binding ([A-Za-z0-9_]+)\}"', self.xaml_text)
        self.assertEqual(len(commands), len(EXPECTED_BUTTONS))
        for command in commands:
            self.assertIn(f"public ICommand {command} {{ get; }}", self.view_model)
        self.assertNotIn("ExportLayoutCommand", commands)
        self.assertNotIn("MapOpsCommand", commands)

    def test_interactive_controls_are_bound(self):
        for item in self.root.iter(NS + "TextBox"):
            self.assertIn("Text", item.attrib)
        for item in self.root.iter(NS + "ComboBox"):
            self.assertTrue("ItemsSource" in item.attrib or "SelectedIndex" in item.attrib)
            self.assertTrue("SelectedItem" in item.attrib or "SelectedIndex" in item.attrib)
        for item in self.root.iter(NS + "ListBox"):
            self.assertIn("ItemsSource", item.attrib)
            self.assertIn("SelectedItem", item.attrib)
        for item in self.root.iter(NS + "DataGrid"):
            self.assertIn("ItemsSource", item.attrib)
        for item in self.root.iter(NS + "CheckBox"):
            self.assertIn("IsChecked", item.attrib)

    def test_advanced_controls_are_consumed_by_processing_commands(self):
        properties = [
            "ContextOpacity", "LocatorMapName", "ProposalValidated", "SelectedRenderMode",
            "SelectedThematicField", "MaxClasses", "SelectedPalette", "SelectedLabelField",
            "LabelsEnabled", "LabelSize", "SelectedPlacement", "LayerOpacity", "ConfirmStyleParameters",
        ]
        for name in properties:
            self.assertGreater(self.view_model.count(name), 1, f"{name} est affiché mais non consommé")
        for parameter in (
            '"render_mode"', '"thematic_field"', '"max_classes"',
            '"palette"', '"label_field"', '"labels_enabled"',
            '"label_size"', '"label_placement"', '"opacity_percent"',
            '"expert_confirmed"', '"context_opacity"', '"locator_map"',
            '"proposal_validated"',
        ):
            self.assertIn(parameter, self.toolbox)

    def test_nine_toolbox_tools_are_preserved(self):
        match = re.search(r"self\.tools\s*=\s*\[(.*?)\]", self.toolbox, re.S)
        self.assertIsNotNone(match)
        tools = [value.strip() for value in match.group(1).replace("\n", " ").split(",") if value.strip()]
        self.assertEqual(tools, ["AuditProject", "AutopilotMap", "CreateLayout", "VectorIntelligence", "RasterIntelligence", "GeoIntelligence", "BatchMaps", "ReplayRecipe", "MapOpsCheck"])

    def test_context_basemap_contract_is_preserved(self):
        sys.path.insert(0, str(ROOT / "toolbox"))
        try:
            from cartomize_core.project_service import ProjectService

            definitions = ProjectService.context_basemap_definitions()
            self.assertEqual([item.key for item in definitions], ["osm", "terrain", "satellite"])
            self.assertEqual(
                [item.label for item in definitions],
                ["OpenStreetMap", "Terrain (OpenTopoMap)", "Imagerie satellitaire"],
            )
            self.assertEqual([item.max_zoom for item in definitions], [19, 17, 19])
        finally:
            sys.path.pop(0)

    def test_version_and_native_arcgis_theme(self):
        self.assertIn('VersionText => "Cartomize 10.5.1"', self.view_model)
        self.assertNotIn("Foreground=", self.xaml_text)
        self.assertNotIn("FontFamily=", self.xaml_text)
        self.assertNotIn("Background=\"#", self.xaml_text)


if __name__ == "__main__":
    unittest.main()
