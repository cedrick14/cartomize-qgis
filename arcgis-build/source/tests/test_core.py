from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "toolbox"))

from cartomize_core.layout import _page_box, _resolve_text, build_layout, is_basemap_layer
from cartomize_core.batch import load_manifest
from cartomize_core.layer_stack import LayerDescriptor, plan_layer_stacks
from cartomize_core.mapops import snapshot
from cartomize_core.raster import analyze_raster, resolve_raster_source
from cartomize_core.raster_themes import THEME_PROFILES, detect_raster_theme
from cartomize_core.recipes import load_recipe, make_recipe, save_recipe
from cartomize_core.symbology import apply_raster_symbology, apply_vector_symbology
from cartomize_core.templates import TemplateCatalog


class TemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = TemplateCatalog(ROOT / "templates_library")
        cls.catalog.reload()

    def test_exactly_24_templates(self):
        self.assertEqual(len(self.catalog.all()), 24)

    def test_all_templates_create_at_least_one_map_frame(self):
        for spec in self.catalog.all():
            self.assertTrue(any(item["type"] == "map_frame" for item in spec.elements), spec.template_id)

    def test_all_elements_fit_page_after_conversion(self):
        for spec in self.catalog.all():
            width, height = spec.page_size_mm
            for item in spec.elements:
                x, y, item_width, item_height = _page_box(item, width, height)
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertLessEqual(x + item_width, width + 1e-6)
                self.assertLessEqual(y + item_height, height + 1e-6)


class RecipeTests(unittest.TestCase):
    def test_round_trip(self):
        recipe = make_recipe(map_name="Map", template_id="administrative/institutionnel", title="Test")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "recipe.json"
            save_recipe(path, recipe)
            self.assertEqual(load_recipe(path)["layout"]["title"], "Test")

    def test_qgis_recipe_v1_is_accepted(self):
        payload = {
            "schema_version": 1,
            "cartomize_version": "10.5.1",
            "objective": "biodiversite",
            "variant": {
                "template_id": "biodiversite/connectivite-ecologique-a4",
                "name": "Institutionnelle",
                "title": "BIODIVERSITÉ",
                "margin_percent": 3.0,
            },
            "sources": "Source : inventaire 2026",
            "visible_only": True,
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "qgis-recipe.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            recipe = load_recipe(path)
            self.assertEqual(recipe["layout"]["template_id"], payload["variant"]["template_id"])
            self.assertEqual(recipe["layout"]["credits"], payload["sources"])


class BatchTests(unittest.TestCase):
    def test_qgis_manifest_contract_is_preserved(self):
        payload = {
            "schema_version": 1,
            "recipe_path": "recipe.json",
            "output_directory": "outputs",
            "dpi": 600,
            "jobs": [{
                "job_id": "carte-1",
                "output_name": "carte-test",
                "output_formats": ["pdf", "qpt"],
            }],
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "manifest.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            manifest = load_manifest(path)
            self.assertEqual(manifest.dpi, 600)
            self.assertEqual(manifest.jobs[0].output_formats, ("pdf", "qpt"))
            self.assertEqual(Path(manifest.output_directory), (Path(folder) / "outputs").resolve())


class LayerStackTests(unittest.TestCase):
    def test_visible_basemap_is_kept_and_moved_to_bottom(self):
        layers = (
            LayerDescriptor("fond", "raster", True),
            LayerDescriptor("routes", "vector"),
            LayerDescriptor("occupation", "raster"),
        )
        plan = plan_layer_stacks(
            layers,
            selected_ids=("occupation",),
            visible_ids=("fond", "routes", "occupation"),
            focus_id="occupation",
        )
        self.assertEqual(plan.main_ids[-1], "fond")
        self.assertIn("fond", plan.locator_ids)
        self.assertEqual(plan.background_ids, ("fond",))


class RasterThemeTests(unittest.TestCase):
    def test_full_qgis_theme_library_is_available(self):
        self.assertEqual(len(THEME_PROFILES), 16)
        self.assertIn("deforestation", {item.key for item in THEME_PROFILES})
        match = detect_raster_theme(
            text="perte forestière deforestation",
            raster_type="categorized",
        )
        self.assertEqual(match.key, "deforestation")


class BasemapTests(unittest.TestCase):
    def test_basemap_detection(self):
        self.assertTrue(is_basemap_layer("World Imagery"))
        self.assertTrue(is_basemap_layer("OpenStreetMap"))
        self.assertFalse(is_basemap_layer("Occupation du sol 2025"))

    def test_layout_legend_cleanup_never_removes_map_layer(self):
        catalog = TemplateCatalog(ROOT / "templates_library")
        spec = catalog.get("administrative/institutionnel")
        basemap = FakeLayer("World Imagery", raster=True)
        thematic = FakeLayer("Occupation du sol 2025", raster=True)
        map_item = FakeMap("Carte principale", [thematic, basemap])
        aprx = FakeProject(map_item)
        before = list(map_item.listLayers())
        result = build_layout(
            FakeArcpy, aprx, map_item, spec,
            layout_name="Test", title="Carte test", subtitle=None, credits=None, open_view=False,
            remove_basemap_from_legend=True,
        )
        self.assertEqual(map_item.listLayers(), before)
        self.assertGreaterEqual(result.basemap_legend_items_removed, 1)
        legends = [item for item in aprx.layouts[0].elements if isinstance(item, FakeLegend)]
        self.assertTrue(legends)
        self.assertFalse(any(is_basemap_layer(item) for item in legends[0].items))

    def test_optional_layout_texts_accept_none(self):
        self.assertEqual(_resolve_text("title", "Titre modèle", None, None, None), "Titre modèle")
        self.assertEqual(_resolve_text("subtitle", "", "Titre", None, None), "")
        self.assertEqual(_resolve_text("text", "Sources : à compléter", "", "", None), "Sources : à compléter")
        self.assertEqual(_resolve_text("text", "Sources : à compléter", "", "", "  IGN 2026  "), "IGN 2026")

    def test_all_layouts_use_arcgis_pro_37_text_types(self):
        catalog = TemplateCatalog(ROOT / "templates_library")
        for spec in catalog.all():
            map_item = FakeMap("Carte", [FakeLayer("Données", feature=True)])
            aprx = FakeProject(map_item)
            build_layout(
                FakeArcpy, aprx, map_item, spec,
                layout_name=f"Test — {spec.template_id}", title="Titre",
                subtitle=None, credits=None, open_view=False,
            )
            self.assertTrue(set(aprx.text_types).issubset({"POINT", "POLYGON"}))


class MapOpsTests(unittest.TestCase):
    def test_snapshot_is_deterministic(self):
        map_item = FakeMap("Map", [FakeLayer("Roads")])
        aprx = FakeProject(map_item)
        first = snapshot(aprx)
        second = snapshot(aprx)
        self.assertEqual(first["fingerprint"], second["fingerprint"])


class RasterTests(unittest.TestCase):
    def test_parameter_text_is_used_instead_of_layer_object(self):
        layer = FakeRasterInputLayer()
        self.assertEqual(
            resolve_raster_source(FakeRasterArcpy, layer, "Mvouti_Couvert_Vegetal.tif"),
            "Mvouti_Couvert_Vegetal.tif",
        )

    def test_layer_data_source_is_used_when_parameter_text_is_absent(self):
        layer = FakeRasterInputLayer()
        self.assertEqual(
            resolve_raster_source(FakeRasterArcpy, layer),
            layer.dataSource,
        )

    def test_qgis_raster_engine_contract_is_preserved(self):
        layer = FakeRasterInputLayer()
        diagnosis = analyze_raster(
            FakeRasterArcpy,
            layer,
            "Mvouti_Couvert_Vegetal.tif",
        )
        self.assertEqual(FakeRasterArcpy.last_raster_input, "Mvouti_Couvert_Vegetal.tif")
        self.assertEqual(diagnosis["raster_type"], "binary")
        self.assertEqual(len(diagnosis["classes"]), 2)
        self.assertIn("inspection", diagnosis)
        self.assertIn("inference", diagnosis)
        self.assertIn("recommended_nodata", diagnosis)
        self.assertIn("anomalies", diagnosis)
        self.assertTrue(diagnosis["non_destructive"])

    def test_categorical_raster_classes_keep_qgis_labels_colors_and_visibility(self):
        layer = FakeStyledRasterLayer()
        diagnosis = {
            "raster_type": "categorized",
            "theme": "land_cover",
            "classes": [
                {"values": [0], "label": "Hors emprise", "color": "#112233", "opacity": 0.25, "visible": False, "show_in_legend": False},
                {"values": [1], "label": "Forêt", "color": "#2E7D32", "opacity": 0.8, "visible": True, "show_in_legend": True, "status": "valide"},
            ],
        }

        result = apply_raster_symbology(FakeStyleProject(), layer, diagnosis, 2)

        self.assertTrue(result["applied"])
        self.assertEqual(result["classes_applied"], 1)
        self.assertEqual(result["classes_hidden"], 1)
        items = layer.symbology.colorizer.groups[0].items
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].label, "Forêt")
        self.assertEqual(items[0].color, {"RGB": [46, 125, 50, 80]})
        self.assertEqual(layer.symbology.colorizer.noDataColor, {"RGB": [0, 0, 0, 0]})


class VectorStyleTests(unittest.TestCase):
    def test_categorized_renderer_uses_qgis_10_5_1_palette(self):
        layer = FakeStyledVectorLayer("UniqueValueRenderer")
        profile = {
            "thematic_field": "classe",
            "label_field": "nom",
            "fields": [{"name": "classe", "semantic_role": "category"}],
        }
        result = apply_vector_symbology(
            FakeStyleProject(), layer, profile,
            mode="Catégorisé", field_name="classe", labels_enabled=False,
        )
        colors = [
            item.symbol.color
            for group in layer.symbology.renderer.groups
            for item in group.items
        ]
        self.assertTrue(result["applied"])
        self.assertEqual(colors[0], {"RGB": [27, 158, 119, 100]})
        self.assertEqual(colors[1], {"RGB": [217, 95, 2, 100]})

    def test_graduated_renderer_uses_qgis_10_5_1_diverging_palette(self):
        layer = FakeStyledVectorLayer("GraduatedColorsRenderer")
        profile = {
            "thematic_field": "variation",
            "fields": [{"name": "variation", "semantic_role": "diverging_quantitative"}],
        }
        result = apply_vector_symbology(
            FakeStyleProject(), layer, profile, 5,
            mode="Gradué — quantiles", field_name="variation", palette="Divergente",
            labels_enabled=False,
        )
        colors = [item.symbol.color for item in layer.symbology.renderer.classBreaks]
        self.assertTrue(result["applied"])
        self.assertEqual(colors[0], {"RGB": [127, 29, 29, 100]})
        self.assertEqual(colors[-1], {"RGB": [30, 58, 138, 100]})


class FakeLayer:
    def __init__(self, name, feature=False, raster=False):
        self.name = name
        self.longName = name
        self.visible = True
        self.isBroken = False
        self.isFeatureLayer = feature
        self.isRasterLayer = raster
        self.URI = f"layer://{name}"


class FakeRasterInputLayer:
    name = "Mvouti_Couvert_Vegetal.tif"
    dataSource = r"C:\data\Mvouti_Couvert_Vegetal.tif"
    isRasterLayer = True
    URI = "layer://mvouti-raster"

    @staticmethod
    def supports(value):
        return str(value).upper() == "DATASOURCE"


class FakeRasterItem:
    def __init__(self, value):
        self.values = [value]
        self.label = str(value)
        self.description = ""
        self.color = {"RGB": [128, 128, 128, 100]}


class FakeRasterItemGroup:
    def __init__(self):
        self.items = [FakeRasterItem(0), FakeRasterItem(1)]


class FakeRasterColorizer:
    def __init__(self):
        self.type = "RasterUniqueValueColorizer"
        self.field = "Value"
        self.groups = [FakeRasterItemGroup()]
        self.noDataColor = {"RGB": [255, 255, 255, 100]}
        self.useDefaultColor = True


class FakeRasterSymbology:
    def __init__(self):
        self.colorizer = FakeRasterColorizer()

    def updateColorizer(self, name):
        if name != "RasterUniqueValueColorizer":
            raise AssertionError(name)
        self.colorizer = FakeRasterColorizer()


class FakeStyledRasterLayer:
    def __init__(self):
        self.symbology = FakeRasterSymbology()
        self.transparency = 0


class FakeStyleProject:
    @staticmethod
    def listColorRamps(*_args):
        return []


class FakeSymbol:
    def __init__(self):
        self.color = {"RGB": [128, 128, 128, 100]}


class FakeVectorItem:
    def __init__(self):
        self.symbol = FakeSymbol()


class FakeVectorGroup:
    def __init__(self):
        self.items = [FakeVectorItem(), FakeVectorItem(), FakeVectorItem()]


class FakeClassBreak:
    def __init__(self):
        self.symbol = FakeSymbol()


class FakeVectorRenderer:
    def __init__(self, kind):
        self.type = kind
        self.symbol = FakeSymbol()
        self.fields = []
        self.groups = [FakeVectorGroup()]
        self.classificationField = ""
        self.breakCount = 5
        self.classificationMethod = ""
        self.classBreaks = [FakeClassBreak() for _ in range(5)]


class FakeVectorSymbology:
    def __init__(self, kind):
        self.renderer = FakeVectorRenderer(kind)

    def updateRenderer(self, kind):
        self.renderer = FakeVectorRenderer(kind)


class FakeStyledVectorLayer:
    def __init__(self, kind):
        self.symbology = FakeVectorSymbology(kind)
        self.transparency = 0
        self.showLabels = False

    @staticmethod
    def listLabelClasses():
        return []


class FakeRasterExtent:
    XMin = 0.0
    YMin = 0.0
    XMax = 40.0
    YMax = 40.0


class FakeSpatialReference:
    factoryCode = 32732
    name = "WGS 84 / UTM zone 32S"


class FakeRasterDescription:
    name = "Mvouti_Couvert_Vegetal.tif"
    nameString = "Mvouti_Couvert_Vegetal.tif"
    catalogPath = r"C:\data\Mvouti_Couvert_Vegetal.tif"
    bandCount = 1
    width = 4
    height = 4
    pixelType = "U8"
    hasRAT = False
    hasColorMap = False
    format = "TIFF"
    spatialReference = FakeSpatialReference()
    extent = FakeRasterExtent()


class FakeRasterObject:
    name = "Mvouti_Couvert_Vegetal.tif"
    catalogPath = r"C:\data\Mvouti_Couvert_Vegetal.tif"
    bandCount = 1
    width = 4
    height = 4
    pixelType = "U8"
    noDataValue = None
    hasRAT = False
    hasColormap = False
    format = "TIFF"
    meanCellWidth = 10.0
    meanCellHeight = 10.0
    extent = FakeRasterExtent()
    bandNames = ["Band_1"]


class FakeRasterPropertyResult:
    def __init__(self, value):
        self.value = value

    def getOutput(self, index):
        return str(self.value)


class FakeRasterManagement:
    VALUES = {"MINIMUM": 0, "MAXIMUM": 1, "MEAN": 0.5, "STD": 0.5}

    @classmethod
    def GetRasterProperties(cls, source, name):
        return FakeRasterPropertyResult(cls.VALUES[name])

    @staticmethod
    def Resample(source, output, cell_size, method):
        raise AssertionError("Le petit raster de test ne doit pas être rééchantillonné.")

    @staticmethod
    def Delete(source):
        return None


class FakeRasterEnvironment:
    scratchGDB = ""
    scratchFolder = ""


class FakeRasterArcpy:
    management = FakeRasterManagement
    env = FakeRasterEnvironment()
    last_raster_input = None

    @staticmethod
    def Describe(source):
        if not isinstance(source, str):
            raise TypeError("expected a raster or layer name")
        return FakeRasterDescription()

    @classmethod
    def Raster(cls, source):
        if not isinstance(source, str):
            raise TypeError("expected a raster or layer name")
        cls.last_raster_input = source
        return FakeRasterObject()

    @staticmethod
    def RasterToNumPyArray(source):
        return np.array(
            [
                [0, 1, 0, 1],
                [1, 0, 1, 0],
                [0, 1, 0, 1],
                [1, 0, 1, 0],
            ],
            dtype=np.uint8,
        )

    @staticmethod
    def ListFields(source):
        return []

    @staticmethod
    def Exists(source):
        return False


class FakeMap:
    def __init__(self, name, layers):
        self.name = name
        self._layers = layers
        self.defaultCamera = FakeCamera()

    def listLayers(self):
        return list(self._layers)


class FakeCamera:
    def __init__(self):
        self.scale = 10000.0

    def setExtent(self, extent):
        self.extent = extent


class FakeElement:
    def __init__(self, name):
        self.name = name
        self.locked = False
        self.elementRotation = 0

    def getDefinition(self, version):
        raise RuntimeError("CIM volontairement absent du double de test")


class FakeMapFrame(FakeElement):
    type = "MAPFRAME_ELEMENT"

    def __init__(self, name, map_item):
        super().__init__(name)
        self.map = map_item
        self.camera = FakeCamera()

    def getLayerExtent(self, layer, selection_only, symbolized_extent):
        return object()


class FakeLegendItem:
    def __init__(self, layer):
        self.name = layer.name
        self.longName = layer.longName


class FakeLegend(FakeElement):
    type = "LEGEND_ELEMENT"

    def __init__(self, name, map_frame):
        super().__init__(name)
        self.items = [FakeLegendItem(layer) for layer in map_frame.map.listLayers()]

    def removeItem(self, item):
        self.items.remove(item)


class FakeSurround(FakeElement):
    type = "MAPSURROUND_ELEMENT"


class FakeLayout:
    def __init__(self, name):
        self.name = name
        self.elements = []

    def createMapFrame(self, geometry, map_item, name):
        element = FakeMapFrame(name, map_item)
        self.elements.append(element)
        return element

    def createMapSurroundElement(self, geometry, surround_type, map_frame, style, name):
        element = FakeLegend(name, map_frame) if surround_type == "LEGEND" else FakeSurround(name)
        self.elements.append(element)
        return element

    def listElements(self):
        return list(self.elements)

    def openView(self):
        return None

    def export(self, export_format):
        return None


class FakeProject:
    def __init__(self, map_item):
        self.map_item = map_item
        self.layouts = []
        self.text_types = []

    def listMaps(self):
        return [self.map_item]

    def listLayouts(self):
        return list(self.layouts)

    def createLayout(self, width, height, units, name):
        layout = FakeLayout(name)
        self.layouts.append(layout)
        return layout

    def createTextElement(self, layout, geometry, text_type, text, size, family, style, style_item, name, locked):
        supported = {"CIRCLE", "ELLIPSE", "LINE", "POINT", "POLYGON"}
        if text_type not in supported:
            raise ValueError(f"Invalid value for text_type: {text_type!r}")
        self.text_types.append(text_type)
        element = FakeElement(name)
        element.type = "TEXT_ELEMENT"
        element.text = text
        layout.elements.append(element)
        return element

    def createGraphicElement(self, layout, geometry, style_item, name, locked):
        element = FakeElement(name)
        element.type = "GRAPHIC_ELEMENT"
        layout.elements.append(element)
        return element


class FakePoint:
    def __init__(self, x, y):
        self.X = x
        self.Y = y


class FakeArcpy:
    Point = FakePoint
    Array = list

    @staticmethod
    def Polygon(points):
        return list(points)

    @staticmethod
    def PointGeometry(point):
        return point


if __name__ == "__main__":
    unittest.main()
