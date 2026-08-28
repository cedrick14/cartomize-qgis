from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "src/Cartomize.ArcGISPro/Services"
WINDOW_CODE = ROOT / "src/Cartomize.ArcGISPro/Views/RasterEngineWindow.xaml.cs"
WINDOW_XAML = ROOT / "src/Cartomize.ArcGISPro/Views/RasterEngineWindow.xaml"


class NativeRasterEngineSmartTests(unittest.TestCase):
    def test_automatic_nodata_is_spatial_and_rendered_transparent(self):
        analysis = (SERVICES / "NativeRasterAnalysisService.cs").read_text(encoding="utf-8")
        style = (SERVICES / "NativeStyleService.cs").read_text(encoding="utf-8")
        self.assertIn("SelectAutomaticNoDataValues", analysis)
        self.assertIn("candidate.BorderPercentage >= 0.65", analysis)
        self.assertIn("candidate.CenterPercentage <= 0.38", analysis)
        self.assertIn("colorizer.NoDataColor = TransparentColor()", style)
        self.assertIn("item.Visible = false", style)

    def test_binary_and_standard_class_schemas_are_available(self):
        analysis = (SERVICES / "NativeRasterAnalysisService.cs").read_text(encoding="utf-8")
        catalog = (SERVICES / "NativeRasterNomenclatureService.cs").read_text(encoding="utf-8")
        self.assertIn('? "binary"', analysis)
        for schema in ("ESA WorldCover", "Google Dynamic World", "GlobeLand30", "Catégories terrestres du GIEC"):
            self.assertIn(schema, catalog)
        for label in ("Carte binaire forêt / non-forêt", "Carte binaire de déforestation", "Carte binaire présence / absence"):
            self.assertIn(label, catalog)

    def test_raster_attribute_table_labels_take_priority(self):
        analysis = (SERVICES / "NativeRasterAnalysisService.cs").read_text(encoding="utf-8")
        catalog = (SERVICES / "NativeRasterNomenclatureService.cs").read_text(encoding="utf-8")
        self.assertIn("raster.GetAttributeTable()", analysis)
        self.assertIn('"Table attributaire raster"', catalog)
        self.assertIn('"Nomenclature intégrée au raster"', catalog)

    def test_black_outline_is_persistent_and_idempotent(self):
        outline = (SERVICES / "NativeRasterOutlineService.cs").read_text(encoding="utf-8")
        window = WINDOW_CODE.read_text(encoding="utf-8")
        self.assertIn('"Cartomize · Contours raster"', outline)
        self.assertIn("graphics!.RemoveElement(existing)", outline)
        self.assertIn("CreateGraphicElement(graphics, extent, symbol", outline)
        self.assertIn("ColorFactory.Instance.BlackRGB", outline)
        self.assertIn("NativeRasterOutlineService.ApplyAsync", window)

    def test_new_controls_are_bound_and_xaml_is_valid(self):
        ET.parse(WINDOW_XAML)
        text = WINDOW_XAML.read_text(encoding="utf-8")
        for binding in ("MaskNoDataAutomatically", "AddBlackOutline", "OutlineWidth"):
            self.assertIn(f"{{Binding {binding}}}", text)


if __name__ == "__main__":
    unittest.main()
