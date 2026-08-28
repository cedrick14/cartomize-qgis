using ArcGIS.Core.CIM;
using ArcGIS.Desktop.Framework.Threading.Tasks;
using ArcGIS.Desktop.Mapping;

namespace Cartomize.ArcGISPro.Services;

internal sealed record NativeRasterClassStyle(double UpperBound, string Label, string Color);

internal sealed record NativeRasterStyleRequest(
    string RenderMode,
    int BandIndex,
    int ClassCount,
    string ClassificationMethod,
    double Minimum,
    double Maximum,
    string Palette,
    IReadOnlyList<NativeRasterClassStyle> Classes);

/// <summary>
/// Symbologie Cartomize appliquée par les RendererDefinition et
/// RasterColorizerDefinition officiels d'ArcGIS Pro.
/// </summary>
internal static class NativeStyleService
{
    // Couleurs du service QGIS Cartomize 10.5.1. Le rendu reste créé par
    // l'API native ArcGIS Pro, puis reçoit exactement la palette choisie.
    private static readonly string[] QualitativePalette =
    [
        "#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e",
        "#e6ab02", "#a6761d", "#1f78b4", "#b2df8a", "#fb9a99",
        "#cab2d6", "#fdbf6f", "#6a3d9a", "#b15928", "#17becf",
    ];

    private static readonly string[] SequentialPalette =
        ["#eff6ff", "#bfdbfe", "#60a5fa", "#2563eb", "#1e3a8a"];

    private static readonly string[] DivergingPalette =
        ["#7f1d1d", "#ef4444", "#f8fafc", "#3b82f6", "#1e3a8a"];

    private static readonly IReadOnlyDictionary<string, string[]> RasterPalettes =
        new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase)
        {
            ["Land Cover"] = ["#1B5E20", "#7CB342", "#F9A825", "#8D6E63", "#D32F2F", "#1565C0", "#90A4AE"],
            ["Forest Dynamics"] = ["#1B5E20", "#D32F2F", "#F57C00", "#66BB6A", "#9E9E9E"],
            ["Deforestation"] = ["#1B5E20", "#D32F2F", "#81C784", "#BDBDBD"],
            ["Forest Degradation"] = ["#0B5D1E", "#A5D66A", "#F9A825", "#D84315", "#BDBDBD"],
            ["Land Cover Change"] = ["#546E7A", "#2E7D32", "#C62828", "#F9A825", "#1565C0"],
            ["Ndvi"] = ["#8B0000", "#D73027", "#FEE08B", "#D9EF8B", "#1A9850", "#006837"],
            ["Elevation"] = ["#1B7837", "#7FBF7B", "#DFC27D", "#A6611A", "#8C6D5A", "#FFFFFF"],
            ["Slope"] = ["#FFFFE5", "#FFF7BC", "#FEC44F", "#D95F0E", "#7F2704"],
            ["Temperature"] = ["#313695", "#4575B4", "#74ADD1", "#FEE090", "#F46D43", "#A50026"],
            ["Precipitation"] = ["#F7FBFF", "#C6DBEF", "#6BAED6", "#2171B5", "#08306B"],
            ["Risk"] = ["#FFFFCC", "#FFEDA0", "#FEB24C", "#F03B20", "#BD0026"],
            ["Probability"] = ["#F7FBFF", "#C6DBEF", "#6BAED6", "#2171B5", "#08306B"],
            ["Categorical"] = ["#2E7D32", "#F9A825", "#1565C0", "#8D6E63", "#6A1B9A", "#546E7A"],
            ["Population"] = ["#FFF5EB", "#FDD0A2", "#FDAE6B", "#E6550D", "#A63603"],
            ["Water"] = ["#F7FBFF", "#C6DBEF", "#6BAED6", "#2171B5", "#08306B"],
            ["Continuous"] = ["#440154", "#3B528B", "#21918C", "#5EC962", "#FDE725"],
            ["Diverging"] = ["#7F1D1D", "#EF4444", "#F8FAFC", "#3B82F6", "#1E3A8A"],
            ["Gray"] = ["#000000", "#404040", "#808080", "#BFBFBF", "#FFFFFF"],
        };

    public static Task ApplyRasterAsync(RasterLayer layer, NativeRasterStyleRequest request)
        => QueuedTask.Run(() =>
        {
            RasterColorizerDefinition definition = request.RenderMode switch
            {
                "Catégoriel" or "Catégorisé" => new UniqueValueColorizerDefinition(),
                "Niveaux de gris" => new StretchColorizerDefinition
                {
                    BandIndex = Math.Max(0, request.BandIndex),
                    StretchType = RasterStretchType.MinimumMaximum,
                },
                _ => new ClassifyColorizerDefinition(
                    "Value",
                    Math.Clamp(request.ClassCount, 2, 64),
                    request.ClassificationMethod.Contains("Intervalles", StringComparison.OrdinalIgnoreCase)
                        ? ClassificationMethod.EqualInterval
                        : ClassificationMethod.Quantile,
                    null),
            };
            if (!layer.CanCreateColorizer(definition))
                definition = new StretchColorizerDefinition
                {
                    BandIndex = Math.Max(0, request.BandIndex),
                    StretchType = RasterStretchType.MinimumMaximum,
                };
            if (!layer.CanCreateColorizer(definition))
                throw new InvalidOperationException("ArcGIS Pro ne peut pas créer ce coloriseur pour le raster sélectionné.");
            var colorizer = layer.CreateColorizer(definition)
                ?? throw new InvalidOperationException("ArcGIS Pro n’a retourné aucun coloriseur.");
            if (colorizer is CIMRasterStretchColorizer stretch && request.Maximum > request.Minimum)
            {
                stretch.UseCustomStretchMinMax = true;
                stretch.CustomStretchMin = request.Minimum;
                stretch.CustomStretchMax = request.Maximum;
            }
            ApplyRasterPalette(colorizer, request.Palette);
            if (colorizer is CIMRasterClassifyColorizer classify && request.Classes.Count > 0)
            {
                classify.MinimumBreak = request.Minimum;
                var classBreaks = classify.ClassBreaks ?? [];
                for (var index = 0; index < Math.Min(classBreaks.Length, request.Classes.Count); index++)
                {
                    var source = request.Classes[index];
                    classBreaks[index].UpperBound = source.UpperBound;
                    classBreaks[index].Label = source.Label;
                    classBreaks[index].Color = ParseColor(source.Color);
                }
                classify.ClassBreaks = classBreaks;
            }
            layer.SetColorizer(colorizer);
        });

    public static Task ApplyAsync(
        Layer layer,
        string renderMode,
        string thematicField,
        int classCount,
        string palette,
        bool labelsEnabled,
        string labelField,
        double labelSize,
        string labelPlacement,
        int opacityPercent)
        => QueuedTask.Run(() =>
        {
            switch (layer)
            {
                case FeatureLayer featureLayer:
                    ApplyFeatureRenderer(featureLayer, renderMode, thematicField, classCount, palette);
                    ApplyLabels(featureLayer, labelsEnabled, labelField, labelSize, labelPlacement);
                    break;
                case RasterLayer rasterLayer:
                    ApplyRasterColorizer(rasterLayer, renderMode, classCount, palette);
                    break;
                default:
                    throw new InvalidOperationException("Cette couche ne prend pas en charge la symbologie Cartomize native.");
            }
            layer.SetTransparency(100 - Math.Clamp(opacityPercent, 0, 100));
        });

    private static void ApplyLabels(
        FeatureLayer layer,
        bool enabled,
        string field,
        double size,
        string placement)
    {
        var hasField = !string.IsNullOrWhiteSpace(field);
        if (hasField)
            layer.SetDisplayField(field);
        if (!hasField)
        {
            layer.SetLabelVisibility(false);
            return;
        }

        if (layer.LabelClasses.Count == 0)
            layer.AddLabelClass("Cartomize");
        foreach (var labelClass in layer.LabelClasses)
        {
            labelClass.SetExpressionEngine(LabelExpressionEngine.Arcade);
            labelClass.SetExpression($"$feature.{field}");
            labelClass.SetLabelVisibility(enabled);
            var symbol = labelClass.GetTextSymbol();
            symbol.SetSize(Math.Clamp(size, 5.0, 36.0));
            labelClass.SetTextSymbol(symbol);

            var properties = labelClass.GetMaplexLabelPlacementProperties();
            ApplyPlacement(properties, placement);
            labelClass.SetMaplexLabelPlacementProperties(properties);
        }
        layer.SetLabelVisibility(enabled);
    }

    private static void ApplyPlacement(CIMMaplexLabelPlacementProperties properties, string placement)
    {
        var value = placement?.Trim() ?? string.Empty;
        properties.PreferHorizontalPlacement = value is "Horizontal" or "Sur le point";
        properties.AlignLabelToLineDirection = value is "Le long de la ligne" or "Courbe";
        properties.CanShiftPointLabel = value is not "Sur le point";
        properties.PrimaryOffset = value == "Autour du point" ? 1.0 : 0.0;
        properties.CanStackLabel = value is "Libre" or "Automatique selon la géométrie" or "";
    }

    private static void ApplyFeatureRenderer(FeatureLayer layer, string mode, string field, int classCount, string palette)
    {
        RendererDefinition definition = mode switch
        {
            "Catégorisé" when !string.IsNullOrWhiteSpace(field)
                => new UniqueValueRendererDefinition(new List<string> { field }) { ValuesLimit = Math.Clamp(classCount, 2, 12) },
            "Gradué — quantiles" when !string.IsNullOrWhiteSpace(field)
                => new GraduatedColorsRendererDefinition
                {
                    ClassificationField = field,
                    ClassificationMethod = ArcGIS.Core.CIM.ClassificationMethod.Quantile,
                    BreakCount = Math.Clamp(classCount, 2, 12),
                },
            _ => new SimpleRendererDefinition(),
        };
        if (!layer.CanCreateRenderer(definition))
            throw new InvalidOperationException("ArcGIS Pro ne peut pas créer ce rendu pour la couche sélectionnée.");
        var renderer = layer.CreateRenderer(definition)
            ?? throw new InvalidOperationException("ArcGIS Pro n’a retourné aucun rendu.");
        ApplyFeaturePalette(renderer, palette);
        layer.SetRenderer(renderer);
    }

    private static void ApplyRasterColorizer(RasterLayer layer, string mode, int classCount, string palette)
    {
        RasterColorizerDefinition definition = mode switch
        {
            "Composition RGB" => new RGBColorizerDefinition
            {
                RedBandIndex = 0,
                GreenBandIndex = 1,
                BlueBandIndex = 2,
                StretchType = ArcGIS.Core.CIM.RasterStretchType.MinimumMaximum,
            },
            "Catégoriel" or "Catégorisé" => new UniqueValueColorizerDefinition(),
            "Continu" or "Gradué — quantiles" => new ClassifyColorizerDefinition(
                "Value",
                Math.Clamp(classCount, 2, 12),
                ArcGIS.Core.CIM.ClassificationMethod.Quantile,
                null),
            _ => new StretchColorizerDefinition(),
        };
        if (!layer.CanCreateColorizer(definition))
            definition = new StretchColorizerDefinition();
        if (!layer.CanCreateColorizer(definition))
            throw new InvalidOperationException("ArcGIS Pro ne peut pas créer ce coloriseur pour le raster sélectionné.");
        var colorizer = layer.CreateColorizer(definition)
            ?? throw new InvalidOperationException("ArcGIS Pro n’a retourné aucun coloriseur.");
        ApplyRasterPalette(colorizer, palette);
        layer.SetColorizer(colorizer);
    }

    private static void ApplyFeaturePalette(CIMRenderer renderer, string palette)
    {
        if (renderer is CIMSimpleRenderer simple)
        {
            simple.Symbol?.Symbol?.SetColor(ParseColor(QualitativePalette[QualitativePalette.Length / 2]));
            return;
        }

        if (renderer is CIMUniqueValueRenderer unique)
        {
            var index = 0;
            foreach (var group in unique.Groups ?? [])
            foreach (var item in group.Classes ?? [])
            {
                item.Symbol?.Symbol?.SetColor(ParseColor(QualitativePalette[index % QualitativePalette.Length]));
                index++;
            }
            return;
        }

        if (renderer is not CIMClassBreaksRenderer graduated)
            return;
        var source = IsDiverging(palette) ? DivergingPalette : SequentialPalette;
        var breaks = graduated.Breaks ?? [];
        var colors = Resample(source, breaks.Length);
        for (var index = 0; index < Math.Min(breaks.Length, colors.Count); index++)
            breaks[index].Symbol?.Symbol?.SetColor(ParseColor(colors[index]));
        graduated.Breaks = breaks;
    }

    private static void ApplyRasterPalette(CIMRasterColorizer colorizer, string palette)
    {
        var source = ResolvePalette(palette, 0);
        if (colorizer is CIMRasterClassifyColorizer classified)
        {
            var breaks = classified.ClassBreaks ?? [];
            var colors = Resample(source, breaks.Length);
            for (var index = 0; index < Math.Min(breaks.Length, colors.Count); index++)
                breaks[index].Color = ParseColor(colors[index]);
            classified.ClassBreaks = breaks;
        }
        else if (colorizer is CIMRasterUniqueValueColorizer unique)
        {
            var index = 0;
            foreach (var group in unique.Groups ?? [])
            foreach (var item in group.Classes ?? [])
            {
                item.Color = ParseColor(source[index % source.Count]);
                index++;
            }
        }
    }

    internal static IReadOnlyList<string> ResolvePalette(string palette, int count)
    {
        var key = palette ?? string.Empty;
        IReadOnlyList<string> source = RasterPalettes.TryGetValue(key, out var rasterPalette)
            ? rasterPalette
            : IsDiverging(key) ? DivergingPalette
            : key.Contains("Qualitative", StringComparison.OrdinalIgnoreCase) ? QualitativePalette
            : SequentialPalette;
        return count > 0 ? Resample(source, count) : source;
    }

    private static bool IsDiverging(string palette)
        => (palette ?? string.Empty).Contains("Diverg", StringComparison.OrdinalIgnoreCase);

    private static IReadOnlyList<string> Resample(IReadOnlyList<string> palette, int count)
    {
        if (count <= 0) return Array.Empty<string>();
        if (count == 1) return [palette[palette.Count / 2]];
        return Enumerable.Range(0, count)
            .Select(index => palette[(int)Math.Round((double)index * (palette.Count - 1) / (count - 1))])
            .ToArray();
    }

    private static CIMColor ParseColor(string value)
    {
        var text = (value ?? string.Empty).Trim().TrimStart('#');
        if (text.Length >= 6
            && byte.TryParse(text[..2], System.Globalization.NumberStyles.HexNumber, System.Globalization.CultureInfo.InvariantCulture, out var red)
            && byte.TryParse(text.Substring(2, 2), System.Globalization.NumberStyles.HexNumber, System.Globalization.CultureInfo.InvariantCulture, out var green)
            && byte.TryParse(text.Substring(4, 2), System.Globalization.NumberStyles.HexNumber, System.Globalization.CultureInfo.InvariantCulture, out var blue))
            return CIMColor.CreateRGBColor(red, green, blue);
        return ColorFactory.Instance.GreyRGB;
    }
}
