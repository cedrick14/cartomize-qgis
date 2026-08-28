from __future__ import annotations

from pathlib import Path
import importlib
import json
import re
import sys
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
HOST_XAML = ROOT / "src/Cartomize.ArcGISPro/Views/CartomizeDockPaneView.xaml"
XAML = ROOT / "src/Cartomize.ArcGISPro/Views/CartomizeContentView.xaml"
VIEW_CODE = ROOT / "src/Cartomize.ArcGISPro/Views/CartomizeDockPaneView.xaml.cs"
CONTENT_CODE = ROOT / "src/Cartomize.ArcGISPro/Views/CartomizeContentView.xaml.cs"
VIEW_MODEL = ROOT / "src/Cartomize.ArcGISPro/Views/CartomizeDockPaneViewModel.cs"
BUTTONS = ROOT / "src/Cartomize.ArcGISPro/Commands/Buttons.cs"
COMMANDS = ROOT / "src/Cartomize.ArcGISPro/Views/DelegateCommand.cs"
DIAGNOSTIC_LOG = ROOT / "src/Cartomize.ArcGISPro/Services/DiagnosticLog.cs"
STARTUP_GUARD = ROOT / "src/Cartomize.ArcGISPro/Services/StartupGuard.cs"
CSPROJ = ROOT / "src/Cartomize.ArcGISPro/Cartomize.ArcGISPro.csproj"
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
        cls.host_root = ET.parse(HOST_XAML).getroot()
        cls.host_xaml_text = HOST_XAML.read_text(encoding="utf-8")
        cls.xaml_text = XAML.read_text(encoding="utf-8")
        cls.view_code = VIEW_CODE.read_text(encoding="utf-8")
        cls.content_code = CONTENT_CODE.read_text(encoding="utf-8")
        cls.view_model = VIEW_MODEL.read_text(encoding="utf-8")
        cls.buttons = BUTTONS.read_text(encoding="utf-8")
        cls.commands = COMMANDS.read_text(encoding="utf-8")
        cls.diagnostic_log = DIAGNOSTIC_LOG.read_text(encoding="utf-8")
        cls.startup_guard = STARTUP_GUARD.read_text(encoding="utf-8")
        cls.csproj = CSPROJ.read_text(encoding="utf-8")
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

    def test_style_inheritance_is_loadable_by_wpf(self):
        # Les styles Esri sont appliqués directement aux contrôles. Cela évite
        # toute résolution de Style.BasedOn pendant la construction du DockPane.
        self.assertNotIn("BasedOn=", self.xaml_text)
        for resource in ("Esri_Button", "Esri_ButtonBorderless", "Esri_DataGrid", "Esri_TextBlockH1", "Esri_TextBlockH3"):
            self.assertIn(f"DynamicResource {resource}", self.xaml_text)

    def test_dockpane_load_failure_cannot_stop_arcgis_pro(self):
        self.assertIn("try", self.view_code)
        self.assertIn("catch (Exception exception)", self.view_code)
        self.assertIn('DiagnosticLog.Write("Chargement XAML du panneau Cartomize", exception)', self.view_code)
        self.assertIn("DiagnosticLog.FilePath", self.view_code)
        self.assertIn("try", self.buttons)
        self.assertIn('DiagnosticLog.Write("Ouverture du panneau Cartomize", exception)', self.buttons)
        self.assertIn('StartupGuard.EnsureInitialized("Clic sur Ouvrir Cartomize")', self.buttons)
        self.assertLess(self.buttons.index("StartupGuard.EnsureInitialized"), self.buttons.index("CartomizeDockPaneViewModel.Show"))
        self.assertIn("catch (Exception exception)", self.commands)
        self.assertIn('DiagnosticLog.Write("Commande asynchrone Cartomize", exception)', self.commands)
        self.assertIn('"ESRI"', self.diagnostic_log)
        self.assertIn('"10.5.1"', self.diagnostic_log)
        self.assertIn('"cartomize.log"', self.diagnostic_log)
        self.assertIn("DispatcherUnhandledException", self.startup_guard)
        self.assertIn("args.Handled = true", self.startup_guard)
        self.assertIn("TaskScheduler.UnobservedTaskException", self.startup_guard)
        self.assertIn("protected override Task InitializeAsync()", self.view_model)
        self.assertIn("InitializeAfterViewLoadedAsync", self.view_model)
        self.assertIn("Loaded += OnLoaded", self.view_code)
        self.assertIn("DispatcherPriority.ContextIdle", self.view_code)
        self.assertIn("ContentHost.Content = new CartomizeContentView()", self.view_code)
        self.assertIn("ContentHost.UpdateLayout()", self.view_code)
        self.assertIn('DiagnosticLog.Write("Chargement XAML du contenu Cartomize", exception)', self.content_code)
        self.assertIn("RefreshProjectSafelyAsync", self.view_model)
        self.assertIn("RefreshLayerFieldsSafelyAsync", self.view_model)
        constructor = self.view_model.split("protected CartomizeDockPaneViewModel()", 1)[1].split("public ObservableCollection", 1)[0]
        self.assertNotIn("LoadTemplateCatalog();", constructor)
        framework_initialize = self.view_model.split("protected override Task InitializeAsync()", 1)[1].split("internal async Task InitializeAfterViewLoadedAsync()", 1)[0]
        self.assertNotIn("LoadTemplateCatalog();", framework_initialize)
        loaded_initialize = self.view_model.split("internal async Task InitializeAfterViewLoadedAsync()", 1)[1].split("protected override void OnActivate", 1)[0]
        self.assertIn("LoadTemplateCatalog();", loaded_initialize)

    def test_arcgis_dockpane_uses_a_lightweight_initial_visual_tree(self):
        self.assertEqual(len(list(self.host_root.iter(NS + "ContentControl"))), 1)
        self.assertNotIn("TabControl", self.host_xaml_text)
        self.assertNotIn("DataGrid", self.host_xaml_text)
        self.assertNotIn("MinWidth", self.host_xaml_text)
        self.assertNotIn("MinWidth", self.root.attrib)

    def test_scrollable_lists_have_bounded_heights(self):
        for item in self.root.iter(NS + "DataGrid"):
            self.assertIn("Height", item.attrib)
            self.assertNotIn("MinHeight", item.attrib)
            self.assertEqual(item.attrib.get("EnableRowVirtualization"), "True")
        for item in self.root.iter(NS + "ListBox"):
            self.assertIn("Height", item.attrib)
            self.assertNotIn("MinHeight", item.attrib)

    def test_arcgis_pro_37_runtime_contract(self):
        self.assertIn("<TargetFramework>net10.0-windows</TargetFramework>", self.csproj)
        self.assertIn("<RuntimeIdentifier>win-x64</RuntimeIdentifier>", self.csproj)
        self.assertIn("<AppendRuntimeIdentifierToOutputPath>false</AppendRuntimeIdentifierToOutputPath>", self.csproj)
        self.assertIn("<CopyLocalLockFileAssemblies>true</CopyLocalLockFileAssemblies>", self.csproj)
        self.assertIn("<PlatformTarget>x64</PlatformTarget>", self.csproj)


if __name__ == "__main__":
    unittest.main()
