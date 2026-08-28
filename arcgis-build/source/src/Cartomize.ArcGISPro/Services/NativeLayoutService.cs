using System.Globalization;
using System.IO;
using System.Text.Json;
using ArcGIS.Core.CIM;
using ArcGIS.Core.Geometry;
using ArcGIS.Desktop.Core;
using ArcGIS.Desktop.Framework.Threading.Tasks;
using ArcGIS.Desktop.Layouts;
using ArcGIS.Desktop.Mapping;

namespace Cartomize.ArcGISPro.Services;

internal sealed record NativeLayoutRequest(
    Map Map,
    string TemplatePath,
    string LayoutName,
    string Title,
    string Subtitle,
    string Credits,
    bool VisibleOnly,
    double MarginPercent,
    bool RemoveBasemapFromLegend,
    Map? LocatorMap = null,
    int ContextOpacityPercent = 100);

internal sealed record NativeLayoutResult(
    Layout Layout,
    string LayoutName,
    int ElementCount,
    int MapFrameCount,
    IReadOnlyList<string> Warnings);

/// <summary>
/// Conversion native des maquettes déclaratives Cartomize 10.5.1 en mises en
/// page ArcGIS Pro. Ce service remplace cartomize_core.layout pour l'add-in.
/// </summary>
internal static class NativeLayoutService
{
    private const double PixelsPerMillimetre = 3.0;
    private const double MillimetresPerInch = 25.4;

    public static async Task<NativeLayoutResult> CreateAsync(NativeLayoutRequest request)
    {
        var template = TemplateDefinition.Load(request.TemplatePath);
        return await QueuedTask.Run(() => CreateOnWorker(request, template));
    }

    public static Task<Layout?> FindAsync(string? layoutName)
        => QueuedTask.Run<Layout?>(() =>
        {
            if (string.IsNullOrWhiteSpace(layoutName)) return null;
            return Project.Current?.GetItems<LayoutProjectItem>()
                .FirstOrDefault(item => item.Name.Equals(layoutName, StringComparison.OrdinalIgnoreCase))
                ?.GetLayout();
        });

    public static Task SynchronizeAsync(
        Layout layout,
        Map map,
        string title,
        string subtitle,
        string credits,
        bool visibleOnly,
        double marginPercent)
        => QueuedTask.Run(() =>
        {
            foreach (var element in layout.GetElementsAsFlattenedList().OfType<TextElement>())
            {
                var name = element.Name.ToLowerInvariant();
                var replacement = name.Contains("subtitle") || name.Contains("sous-titre")
                    ? subtitle
                    : name.Contains("title") || name.Contains("titre")
                        ? title
                        : name.Contains("source") || name.Contains("credit") || name.Contains("crédit")
                            ? credits
                            : string.Empty;
                if (string.IsNullOrWhiteSpace(replacement)) continue;
                var graphic = element.GetGraphic();
                if (graphic is not CIMTextGraphic textGraphic) continue;
                textGraphic.Text = replacement;
                element.SetGraphic(graphic);
            }

            var reference = ReferenceLayers(map, visibleOnly).FirstOrDefault();
            if (reference is null) return;
            foreach (var frame in layout.GetElementsAsFlattenedList().OfType<MapFrame>())
            {
                frame.SetMap(map);
                frame.SetCamera(reference, false);
                var camera = frame.Camera;
                camera.Scale *= 1.0 + Math.Clamp(marginPercent, 0, 50) / 100.0;
                frame.SetCamera(camera);
            }
        });

    public static Task OptimizeAsync(Layout layout)
        => QueuedTask.Run(() =>
        {
            var page = layout.GetPage();
            foreach (var element in layout.GetElementsAsFlattenedList())
            {
                var width = Math.Min(element.GetWidth(), page.Width);
                var height = Math.Min(element.GetHeight(), page.Height);
                element.SetWidth(width);
                element.SetHeight(height);
                element.SetX(Math.Clamp(element.GetX(), 0, Math.Max(0, page.Width - width)));
                element.SetY(Math.Clamp(element.GetY(), 0, Math.Max(0, page.Height - height)));
            }
        });

    public static Task ExportAsync(Layout layout, string outputPath, int dpi = 600)
        => QueuedTask.Run(() =>
        {
            var fullPath = Path.GetFullPath(outputPath);
            Directory.CreateDirectory(Path.GetDirectoryName(fullPath) ?? Module.UserDataDirectory);
            var extension = Path.GetExtension(fullPath).ToLowerInvariant();
            if (extension == ".pagx")
            {
                layout.SaveAsFile(fullPath, true);
                return;
            }

            ExportFormat format = extension switch
            {
                ".pdf" => new PDFFormat
                {
                    OutputFileName = fullPath,
                    Resolution = Math.Clamp(dpi, 96, 1200),
                    DoCompressVectorGraphics = true,
                    DoEmbedFonts = true,
                    HasGeoRefInfo = true,
                    ImageQuality = ImageQuality.Best,
                },
                ".png" => new PNGFormat
                {
                    OutputFileName = fullPath,
                    Resolution = Math.Clamp(dpi, 96, 1200),
                },
                ".svg" => new SVGFormat
                {
                    OutputFileName = fullPath,
                    Resolution = Math.Clamp(dpi, 96, 1200),
                },
                _ => throw new InvalidOperationException("Formats pris en charge : PDF, PNG, SVG et PAGX."),
            };
            if (!format.ValidateOutputFilePath())
                throw new InvalidOperationException($"Le fichier d'export n'est pas accessible : {fullPath}");
            layout.Export(format);
        });

    private static NativeLayoutResult CreateOnWorker(NativeLayoutRequest request, TemplateDefinition template)
    {
        var width = ToInches(template.PageWidthMillimetres);
        var height = ToInches(template.PageHeightMillimetres);
        var layout = LayoutFactory.Instance.CreateLayout(width, height, LinearUnit.Inches);
        var name = UniqueLayoutName(request.LayoutName);
        layout.SetName(name);
        SetContextOpacity(request.Map, request.ContextOpacityPercent);
        if (request.LocatorMap is not null && request.LocatorMap != request.Map)
            SetContextOpacity(request.LocatorMap, request.ContextOpacityPercent);

        var frames = new Dictionary<string, MapFrame>(StringComparer.OrdinalIgnoreCase);
        var warnings = new List<string>();
        var created = 0;
        foreach (var item in template.Elements.OrderBy(item => item.ZIndex).ThenBy(item => item.Id, StringComparer.Ordinal))
        {
            if (item.Type is "legend" or "scale_bar" or "north_arrow") continue;
            var envelope = ItemEnvelope(item, template);
            switch (item.Type)
            {
                case "map_frame":
                {
                    var role = item.ContentText("role", frames.Count == 0 ? "main" : "locator");
                    var map = request.LocatorMap is not null && role is ("locator" or "overview" or "situation")
                        ? request.LocatorMap
                        : request.Map;
                    var frame = ElementFactory.Instance.CreateMapFrameElement(layout, envelope, map, item.Id);
                    frames[item.Id] = frame;
                    created++;
                    break;
                }
                case "title":
                case "subtitle":
                case "text":
                    CreateText(layout, item, envelope, ResolveText(item, request));
                    created++;
                    break;
                case "shape":
                case "chart":
                case "table":
                    CreateShape(layout, item, envelope);
                    created++;
                    if (item.Type is "chart" or "table")
                    {
                        var label = item.Type == "chart" ? "ZONE DE GRAPHIQUE" : "ZONE DE TABLEAU";
                        CreatePlaceholderLabel(layout, item.Id, envelope, label);
                        created++;
                    }
                    break;
            }
        }

        var primary = template.Elements
            .Where(item => item.Type == "map_frame")
            .OrderByDescending(item => item.ContentText("role", string.Empty) == "main")
            .Select(item => frames.GetValueOrDefault(item.Id))
            .FirstOrDefault(frame => frame is not null)
            ?? frames.Values.FirstOrDefault()
            ?? throw new InvalidOperationException("La maquette ne contient aucun cadre cartographique exploitable.");

        ConfigureMapFrames(request, template, frames);
        foreach (var item in template.Elements.OrderBy(item => item.ZIndex).ThenBy(item => item.Id, StringComparer.Ordinal))
        {
            if (item.Type is not ("legend" or "scale_bar" or "north_arrow")) continue;
            var linkedId = item.ContentText("map_id", string.Empty);
            var linked = frames.GetValueOrDefault(linkedId) ?? primary;
            try
            {
                CreateSurround(layout, item, ItemEnvelope(item, template), linked);
                created++;
            }
            catch (Exception exception)
            {
                warnings.Add($"{item.Id} : {exception.Message}");
            }
        }
        return new NativeLayoutResult(layout, name, created, frames.Count, warnings);
    }

    private static void ConfigureMapFrames(
        NativeLayoutRequest request,
        TemplateDefinition template,
        IReadOnlyDictionary<string, MapFrame> frames)
    {
        foreach (var item in template.Elements.Where(item => item.Type == "map_frame"))
        {
            if (!frames.TryGetValue(item.Id, out var frame)) continue;
            var map = frame.Map;
            var reference = ReferenceLayers(map, request.VisibleOnly).FirstOrDefault();
            if (reference is null) continue;
            frame.SetCamera(reference, false);
            var camera = frame.Camera;
            var role = item.ContentText("role", "main");
            camera.Scale *= role == "locator"
                ? 3.0
                : 1.0 + Math.Clamp(request.MarginPercent, 0, 50) / 100.0;
            frame.SetCamera(camera);
        }
    }

    private static IEnumerable<Layer> ReferenceLayers(Map map, bool visibleOnly)
        => map.GetLayersAsFlattenedList()
            .Where(layer => layer is BasicFeatureLayer or RasterLayer)
            .Where(layer => !visibleOnly || layer.IsVisible)
            .Where(layer => !IsBasemap(layer.Name));

    private static void CreateText(Layout layout, TemplateElement item, Envelope envelope, string text)
    {
        var font = item.StyleText("fontFamily", "Arial").Split(',')[0].Trim();
        var fontStyle = item.StyleText("fontWeight", "normal").Equals("bold", StringComparison.OrdinalIgnoreCase)
            ? "Bold"
            : "Regular";
        var symbol = SymbolFactory.Instance.ConstructTextSymbol(
            ParseColor(item.StyleText("fill", "#000000")),
            Math.Max(7, item.StyleNumber("fontSize", 10)),
            font,
            fontStyle);
        ElementFactory.Instance.CreateTextGraphicElement(
            layout,
            TextType.RectangleParagraph,
            envelope,
            symbol,
            text,
            item.Id);
    }

    private static void CreateShape(Layout layout, TemplateElement item, Envelope envelope)
    {
        var stroke = SymbolFactory.Instance.ConstructStroke(
            ParseColor(item.StyleText("stroke", "#000000")),
            Math.Max(0, item.StyleNumber("strokeWidth", 0.5)),
            SimpleLineStyle.Solid);
        var symbol = SymbolFactory.Instance.ConstructPolygonSymbol(
            ParseColor(item.StyleText("fill", "#FFFFFF")),
            SimpleFillStyle.Solid,
            stroke);
        ElementFactory.Instance.CreateGraphicElement(layout, envelope, symbol, item.Id);
    }

    private static void CreatePlaceholderLabel(Layout layout, string id, Envelope envelope, string label)
    {
        var symbol = SymbolFactory.Instance.ConstructTextSymbol(ColorFactory.Instance.BlackRGB, 7, "Arial", "Regular");
        ElementFactory.Instance.CreateTextGraphicElement(
            layout,
            TextType.PointText,
            new Coordinate2D(envelope.XMin + ToInches(3), envelope.YMin + ToInches(3)).ToMapPoint(),
            symbol,
            label,
            $"{id}-label");
    }

    private static void CreateSurround(Layout layout, TemplateElement item, Envelope envelope, MapFrame frame)
    {
        switch (item.Type)
        {
            case "legend":
                ElementFactory.Instance.CreateMapSurroundElement(
                    layout,
                    envelope,
                    new LegendInfo { MapFrameName = frame.Name },
                    item.Id);
                break;
            case "scale_bar":
                ElementFactory.Instance.CreateMapSurroundElement(
                    layout,
                    envelope,
                    new ScaleBarInfo { MapFrameName = frame.Name },
                    item.Id);
                break;
            case "north_arrow":
            {
                var style = Project.Current?.GetItems<StyleProjectItem>()
                    .FirstOrDefault(value => value.Name.Equals("ArcGIS 2D", StringComparison.OrdinalIgnoreCase));
                var northArrow = style?.SearchNorthArrows("ArcGIS North 10").FirstOrDefault();
                if (northArrow is null)
                    throw new InvalidOperationException("Le style de flèche nord ArcGIS 2D est indisponible.");
                ElementFactory.Instance.CreateMapSurroundElement(
                    layout,
                    envelope.Center,
                    new NorthArrowInfo { MapFrameName = frame.Name, NorthArrowStyleItem = northArrow },
                    item.Id);
                break;
            }
        }
    }

    private static string ResolveText(TemplateElement item, NativeLayoutRequest request)
    {
        var raw = item.ContentText("text", string.Empty);
        if (item.Type == "title") return string.IsNullOrWhiteSpace(request.Title) ? raw : request.Title;
        if (item.Type == "subtitle") return string.IsNullOrWhiteSpace(request.Subtitle) ? raw : request.Subtitle;
        if (raw.StartsWith("Sources", StringComparison.CurrentCultureIgnoreCase) && !string.IsNullOrWhiteSpace(request.Credits))
            return request.Credits;
        return raw;
    }

    private static Envelope ItemEnvelope(TemplateElement item, TemplateDefinition template)
    {
        var pageWidth = ToInches(template.PageWidthMillimetres);
        var pageHeight = ToInches(template.PageHeightMillimetres);
        var x = Math.Clamp(ToInches(item.X / PixelsPerMillimetre), 0, Math.Max(0, pageWidth - 0.01));
        var top = Math.Clamp(ToInches(item.Y / PixelsPerMillimetre), 0, Math.Max(0, pageHeight - 0.01));
        var width = Math.Clamp(ToInches(item.Width / PixelsPerMillimetre), 0.01, Math.Max(0.01, pageWidth - x));
        var height = Math.Clamp(ToInches(item.Height / PixelsPerMillimetre), 0.01, Math.Max(0.01, pageHeight - top));
        var bottom = pageHeight - top - height;
        return EnvelopeBuilderEx.CreateEnvelope(x, bottom, x + width, bottom + height);
    }

    private static void SetContextOpacity(Map map, int opacityPercent)
    {
        var transparency = 100 - Math.Clamp(opacityPercent, 0, 100);
        foreach (var layer in map.GetLayersAsFlattenedList().Where(layer => IsBasemap(layer.Name)))
            layer.SetTransparency(transparency);
    }

    private static bool IsBasemap(string name)
    {
        var value = name.ToLowerInvariant();
        return new[] { "basemap", "fond de carte", "world topo", "topographic", "world imagery", "hillshade", "openstreetmap", "terrain", "light gray", "dark gray" }
            .Any(value.Contains);
    }

    private static string UniqueLayoutName(string requested)
    {
        var baseName = string.IsNullOrWhiteSpace(requested) ? "Cartomize — Mise en page" : requested.Trim();
        var names = Project.Current?.GetItems<LayoutProjectItem>()
            .Select(item => item.Name)
            .ToHashSet(StringComparer.OrdinalIgnoreCase) ?? [];
        if (!names.Contains(baseName)) return baseName;
        var index = 2;
        while (names.Contains($"{baseName} ({index})")) index++;
        return $"{baseName} ({index})";
    }

    private static CIMColor ParseColor(string value)
    {
        var text = (value ?? string.Empty).Trim().TrimStart('#');
        if (text.Length < 6
            || !int.TryParse(text[..2], NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var red)
            || !int.TryParse(text.Substring(2, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var green)
            || !int.TryParse(text.Substring(4, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var blue))
            return ColorFactory.Instance.BlackRGB;
        return CIMColor.CreateRGBColor(red, green, blue);
    }

    private static double ToInches(double millimetres) => millimetres / MillimetresPerInch;

    private sealed record TemplateDefinition(
        double PageWidthMillimetres,
        double PageHeightMillimetres,
        IReadOnlyList<TemplateElement> Elements)
    {
        public static TemplateDefinition Load(string path)
        {
            if (!File.Exists(path))
                throw new FileNotFoundException("La maquette Cartomize est introuvable.", path);
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var root = document.RootElement;
            var layout = root.GetProperty("layout_json");
            var pageFormat = CartomizeDataService.Text(root, "page_format", CartomizeDataService.Text(layout, "page_format", "A4 paysage"));
            var size = pageFormat switch
            {
                "A4 portrait" => (210d, 297d),
                "A3 paysage" => (420d, 297d),
                "A3 portrait" => (297d, 420d),
                _ => (297d, 210d),
            };
            var elements = layout.GetProperty("elements")
                .EnumerateArray()
                .Select((value, index) => TemplateElement.FromJson(value, index))
                .Take(250)
                .ToArray();
            return new TemplateDefinition(size.Item1, size.Item2, elements);
        }
    }

    private sealed record TemplateElement(
        string Id,
        string Type,
        double X,
        double Y,
        double Width,
        double Height,
        int ZIndex,
        JsonElement Style,
        JsonElement Content)
    {
        public string StyleText(string name, string fallback) => CartomizeDataService.Text(Style, name, fallback);
        public double StyleNumber(string name, double fallback) => CartomizeDataService.Number(Style, name, fallback);
        public string ContentText(string name, string fallback) => CartomizeDataService.Text(Content, name, fallback);

        public static TemplateElement FromJson(JsonElement value, int index)
        {
            var style = value.TryGetProperty("style", out var styleValue) ? styleValue.Clone() : default;
            var content = value.TryGetProperty("content", out var contentValue) ? contentValue.Clone() : default;
            return new TemplateElement(
                CartomizeDataService.Text(value, "id", $"element-{index}"),
                CartomizeDataService.Text(value, "type"),
                CartomizeDataService.Number(value, "x"),
                CartomizeDataService.Number(value, "y"),
                Math.Max(1, CartomizeDataService.Number(value, "width", 100)),
                Math.Max(1, CartomizeDataService.Number(value, "height", 40)),
                (int)CartomizeDataService.Number(value, "z_index", index),
                style,
                content);
        }
    }
}
