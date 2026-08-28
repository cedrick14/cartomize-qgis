using System.Globalization;
using System.Text;

namespace Cartomize.ArcGISPro.Services;

internal sealed record NativeRasterAttributeClass(double Value, string Label, string Color);

internal sealed record NativeRasterClassProposal(
    double Value,
    string Label,
    string Color,
    double Confidence,
    string Source);

internal sealed record NativeRasterRangeProposal(
    double LowerBound,
    double UpperBound,
    string Label,
    string Color,
    double Confidence,
    string Source);

internal sealed record NativeRasterNomenclature(
    string Key,
    string Name,
    string Theme,
    string Palette,
    double Confidence,
    IReadOnlyList<string> Rationale,
    IReadOnlyList<NativeRasterClassProposal> Classes);

/// <summary>
/// Catalogue déterministe de nomenclatures raster. Une norme n'est annoncée
/// que lorsque les codes et le contexte concordent; une table attributaire du
/// raster reste toujours prioritaire sur une proposition Cartomize.
/// </summary>
internal static class NativeRasterNomenclatureService
{
    private sealed record NamedClass(string Label, string Color);

    private sealed record CodeSchema(
        string Key,
        string Name,
        string Theme,
        string Palette,
        IReadOnlyDictionary<int, NamedClass> Classes,
        IReadOnlyList<string> Keywords);

    private static readonly string[] QualitativeColors =
    [
        "#1B5E20", "#7CB342", "#F9A825", "#8D6E63", "#D32F2F", "#1565C0",
        "#6A1B9A", "#00838F", "#EF6C00", "#546E7A", "#AD1457", "#2E7D32",
    ];

    private static readonly CodeSchema[] Schemas =
    [
        new(
            "esa_worldcover",
            "ESA WorldCover",
            "land_cover",
            "Land Cover",
            new Dictionary<int, NamedClass>
            {
                [10] = new("Couvert arboré", "#006400"),
                [20] = new("Formations arbustives", "#FFBB22"),
                [30] = new("Prairies", "#FFFF4C"),
                [40] = new("Terres cultivées", "#F096FF"),
                [50] = new("Zones bâties", "#FA0000"),
                [60] = new("Sol nu / végétation clairsemée", "#B4B4B4"),
                [70] = new("Neige et glace", "#F0F0F0"),
                [80] = new("Eau permanente", "#0064C8"),
                [90] = new("Zone humide herbacée", "#0096A0"),
                [95] = new("Mangrove", "#00CF75"),
                [100] = new("Mousses et lichens", "#FAE6A0"),
            },
            ["worldcover", "esa world cover", "esa_worldcover"]),
        new(
            "dynamic_world",
            "Google Dynamic World",
            "land_cover",
            "Land Cover",
            new Dictionary<int, NamedClass>
            {
                [0] = new("Eau", "#419BDF"),
                [1] = new("Arbres", "#397D49"),
                [2] = new("Herbe", "#88B053"),
                [3] = new("Végétation inondée", "#7A87C6"),
                [4] = new("Cultures", "#E49635"),
                [5] = new("Arbustes et broussailles", "#DFC35A"),
                [6] = new("Zone bâtie", "#C4281B"),
                [7] = new("Sol nu", "#A59B8F"),
                [8] = new("Neige et glace", "#B39FE1"),
            },
            ["dynamic world", "dynamic_world"]),
        new(
            "globeland30",
            "GlobeLand30",
            "land_cover",
            "Land Cover",
            new Dictionary<int, NamedClass>
            {
                [10] = new("Terres cultivées", "#FFFF64"),
                [20] = new("Forêt", "#006400"),
                [30] = new("Prairies", "#96FF00"),
                [40] = new("Formations arbustives", "#A0B432"),
                [50] = new("Zones humides", "#00FFFF"),
                [60] = new("Eau", "#0064FF"),
                [70] = new("Toundra", "#B4C8A0"),
                [80] = new("Surfaces artificialisées", "#FA0000"),
                [90] = new("Sol nu", "#BEBEBE"),
                [100] = new("Neige et glace", "#FFFFFF"),
            },
            ["globeland30", "globe land 30"]),
        new(
            "ipcc_land_categories",
            "Catégories terrestres du GIEC",
            "land_cover",
            "Land Cover",
            new Dictionary<int, NamedClass>
            {
                [1] = new("Terres forestières", "#1B5E20"),
                [2] = new("Terres cultivées", "#F9A825"),
                [3] = new("Prairies", "#7CB342"),
                [4] = new("Zones humides", "#1565C0"),
                [5] = new("Établissements", "#D32F2F"),
                [6] = new("Autres terres", "#8D6E63"),
            },
            ["ipcc", "giec", "land categories"]),
    ];

    public static NativeRasterNomenclature ProposeCategorical(
        string context,
        string rasterType,
        string detectedTheme,
        IReadOnlyCollection<double> values,
        IReadOnlyList<NativeRasterAttributeClass> attributeClasses)
    {
        var ordered = values.Where(double.IsFinite).Distinct().OrderBy(value => value).ToArray();
        var attributeByValue = attributeClasses
            .GroupBy(item => item.Value)
            .ToDictionary(group => group.Key, group => group.First());
        var labelled = ordered.Count(value =>
            FindAttribute(attributeByValue, value) is { Label.Length: > 0 });
        if (ordered.Length > 0 && labelled >= Math.Max(2, (int)Math.Ceiling(ordered.Length * 0.60)))
        {
            var classes = ordered.Select((value, index) =>
            {
                var attribute = FindAttribute(attributeByValue, value);
                return new NativeRasterClassProposal(
                    value,
                    string.IsNullOrWhiteSpace(attribute?.Label) ? $"Classe {Pretty(value)}" : attribute.Label,
                    ValidColor(attribute?.Color) ? attribute!.Color : QualitativeColors[index % QualitativeColors.Length],
                    attribute is null ? 0.72 : 0.995,
                    attribute is null ? "Code détecté" : "Table attributaire raster");
            }).ToArray();
            return new NativeRasterNomenclature(
                "raster_attribute_table",
                "Nomenclature intégrée au raster",
                detectedTheme,
                PaletteForTheme(detectedTheme),
                0.995,
                ["Les libellés de la table attributaire raster sont conservés en priorité."],
                classes);
        }

        if (rasterType == "binary" && ordered.Length == 2)
            return BinaryNomenclature(context, detectedTheme, ordered);

        var normalized = Normalize(context);
        var integerCodes = ordered.All(IntegerLike)
            ? ordered.Select(value => (int)Math.Round(value)).ToArray()
            : [];
        var matches = Schemas
            .Select(schema => (Schema: schema, Score: SchemaScore(schema, normalized, integerCodes)))
            .Where(item => item.Score >= 0.70)
            .OrderByDescending(item => item.Score)
            .ToArray();
        var best = matches.FirstOrDefault();
        if (best.Schema is not null)
        {
            var classes = ordered.Select((value, index) =>
            {
                var code = (int)Math.Round(value);
                var named = best.Schema.Classes.GetValueOrDefault(code);
                return new NativeRasterClassProposal(
                    value,
                    named?.Label ?? $"Classe {Pretty(value)}",
                    named?.Color ?? QualitativeColors[index % QualitativeColors.Length],
                    best.Score,
                    best.Schema.Name);
            }).ToArray();
            return new NativeRasterNomenclature(
                best.Schema.Key,
                best.Schema.Name,
                best.Schema.Theme,
                best.Schema.Palette,
                Math.Round(best.Score, 4),
                [$"Les codes observés concordent avec {best.Schema.Name} et son contexte thématique."],
                classes);
        }

        var theme = string.IsNullOrWhiteSpace(detectedTheme) ? "categorical" : detectedTheme;
        var genericClasses = ordered.Select((value, index) =>
        {
            var attribute = FindAttribute(attributeByValue, value);
            var prefix = theme == "land_cover" ? "Occupation du sol" : "Classe";
            return new NativeRasterClassProposal(
                value,
                string.IsNullOrWhiteSpace(attribute?.Label) ? $"{prefix} · code {Pretty(value)}" : attribute.Label,
                ValidColor(attribute?.Color) ? attribute!.Color : QualitativeColors[index % QualitativeColors.Length],
                attribute is null ? 0.60 : 0.95,
                attribute is null ? "Schéma qualitatif proposé" : "Table attributaire raster");
        }).ToArray();
        return new NativeRasterNomenclature(
            theme == "land_cover" ? "land_cover_generic" : "categorical_generic",
            theme == "land_cover" ? "Occupation du sol — codes à confirmer" : "Classification raster — codes à confirmer",
            theme,
            PaletteForTheme(theme),
            0.60,
            ["Aucune norme de codes n'est démontrée; Cartomize conserve chaque code et propose une palette modifiable."],
            genericClasses);
    }

    public static IReadOnlyList<NativeRasterRangeProposal> ProposeContinuous(
        string theme,
        double minimum,
        double maximum,
        IReadOnlyList<double> quantileBreaks)
    {
        var key = (theme ?? string.Empty).Trim().ToLowerInvariant();
        var thresholds = key switch
        {
            "ndvi" when minimum >= -1.05 && maximum <= 1.05
                => ClipThresholds(minimum, maximum, [0, 0.2, 0.4, 0.6, 1.0]),
            "probability" when minimum >= 0 && maximum <= 1.000001
                => ClipThresholds(minimum, maximum, [0.2, 0.4, 0.6, 0.8, 1.0]),
            "probability" when minimum >= 0 && maximum <= 100.0001
                => ClipThresholds(minimum, maximum, [20, 40, 60, 80, 100]),
            "slope" when minimum >= 0 && maximum <= 90.0001
                => ClipThresholds(minimum, maximum, [5, 15, 30, 45, 90]),
            _ => quantileBreaks.Where(value => value > minimum).Append(maximum).Distinct().OrderBy(value => value).ToArray(),
        };
        if (thresholds.Count == 0) thresholds = [maximum];
        var colors = ContinuousColors(key, thresholds.Count);
        var result = new List<NativeRasterRangeProposal>();
        var lower = minimum;
        for (var index = 0; index < thresholds.Count; index++)
        {
            var upper = thresholds[index];
            if (upper < lower) continue;
            result.Add(new NativeRasterRangeProposal(
                lower,
                upper,
                RangeLabel(key, index, thresholds.Count, lower, upper),
                colors[index],
                key is "ndvi" or "probability" or "slope" ? 0.86 : 0.72,
                key is "ndvi" or "probability" or "slope" ? "Seuils thématiques" : "Quantiles valides"));
            lower = upper;
        }
        return result;
    }

    private static NativeRasterNomenclature BinaryNomenclature(string context, string theme, IReadOnlyList<double> values)
    {
        var text = Normalize($"{context} {theme}");
        (string Key, string Name, string Theme, string Low, string High, string LowColor, string HighColor, double Confidence) schema =
            text.Contains("deforest", StringComparison.Ordinal) || text.Contains("forest loss", StringComparison.Ordinal)
                ? ("binary_deforestation", "Carte binaire de déforestation", "deforestation", "Forêt stable / absence de perte", "Déforestation / perte forestière", "#1B5E20", "#D32F2F", 0.91)
            : text.Contains("forest", StringComparison.Ordinal) || text.Contains("foret", StringComparison.Ordinal)
                ? ("binary_forest", "Carte binaire forêt / non-forêt", "forest_dynamics", "Non-forêt", "Forêt", "#BDBDBD", "#1B5E20", 0.86)
            : text.Contains("water", StringComparison.Ordinal) || text.Contains("eau", StringComparison.Ordinal)
                ? ("binary_water", "Carte binaire eau / non-eau", "categorical", "Non-eau", "Eau", "#D9D9D9", "#1565C0", 0.86)
            : text.Contains("bati", StringComparison.Ordinal) || text.Contains("built", StringComparison.Ordinal) || text.Contains("urban", StringComparison.Ordinal)
                ? ("binary_built", "Carte binaire bâti / non-bâti", "land_cover", "Non-bâti", "Bâti", "#E0E0E0", "#D32F2F", 0.86)
            : text.Contains("change", StringComparison.Ordinal) || text.Contains("changement", StringComparison.Ordinal)
                ? ("binary_change", "Carte binaire de changement", "land_cover_change", "Stable", "Changement", "#546E7A", "#F57C00", 0.84)
                : ("binary_presence", "Carte binaire présence / absence", "categorical", "Absence", "Présence", "#E0E0E0", "#2E7D32", 0.72);
        return new NativeRasterNomenclature(
            schema.Key,
            schema.Name,
            schema.Theme,
            schema.Theme == "deforestation" ? "Deforestation" : PaletteForTheme(schema.Theme),
            schema.Confidence,
            ["Deux codes valides ont été détectés dans une bande unique; le sens des classes reste modifiable."],
            [
                new(values[0], schema.Low, schema.LowColor, schema.Confidence, schema.Name),
                new(values[1], schema.High, schema.HighColor, schema.Confidence, schema.Name),
            ]);
    }

    private static double SchemaScore(CodeSchema schema, string normalizedContext, IReadOnlyList<int> codes)
    {
        if (codes.Count < 2 || codes.Any(code => !schema.Classes.ContainsKey(code))) return 0;
        var keyword = schema.Keywords.Any(item => normalizedContext.Contains(Normalize(item), StringComparison.Ordinal));
        var exact = codes.Count == schema.Classes.Count && schema.Classes.Keys.All(codes.Contains);
        var distinctive = schema.Key == "esa_worldcover" && codes.Contains(95)
                          || schema.Key == "dynamic_world" && exact;
        if (!keyword && !exact && !distinctive) return 0;
        var coverage = codes.Count / (double)schema.Classes.Count;
        return Math.Clamp(0.62 + coverage * 0.20 + (keyword ? 0.14 : 0) + (exact ? 0.04 : 0), 0, 0.99);
    }

    private static NativeRasterAttributeClass? FindAttribute(
        IReadOnlyDictionary<double, NativeRasterAttributeClass> values,
        double searched)
        => values.FirstOrDefault(item => SameNumber(item.Key, searched)).Value;

    private static IReadOnlyList<double> ClipThresholds(double minimum, double maximum, IReadOnlyList<double> candidates)
        => candidates.Where(value => value > minimum && value <= maximum)
            .Append(maximum)
            .Distinct()
            .OrderBy(value => value)
            .ToArray();

    private static IReadOnlyList<string> ContinuousColors(string theme, int count)
    {
        IReadOnlyList<string> source = theme switch
        {
            "ndvi" => ["#8B0000", "#D73027", "#FEE08B", "#7CB342", "#006837"],
            "slope" => ["#FFFFE5", "#FFF7BC", "#FEC44F", "#D95F0E", "#7F2704"],
            "risk" => ["#FFFFCC", "#FFEDA0", "#FEB24C", "#F03B20", "#BD0026"],
            "temperature" => ["#313695", "#74ADD1", "#FEE090", "#F46D43", "#A50026"],
            "precipitation" or "probability" => ["#F7FBFF", "#C6DBEF", "#6BAED6", "#2171B5", "#08306B"],
            "elevation" => ["#1B7837", "#7FBF7B", "#DFC27D", "#A6611A", "#FFFFFF"],
            _ => ["#440154", "#3B528B", "#21918C", "#5EC962", "#FDE725"],
        };
        if (count == 1) return [source[source.Count / 2]];
        return Enumerable.Range(0, count)
            .Select(index => source[(int)Math.Round(index * (source.Count - 1d) / Math.Max(1, count - 1))])
            .ToArray();
    }

    private static string RangeLabel(string theme, int index, int count, double lower, double upper)
    {
        string[] fiveLevels = ["Très faible", "Faible", "Modéré", "Élevé", "Très élevé"];
        string[] ndvi = ["Eau / sol nu", "Végétation très faible", "Végétation faible", "Végétation modérée", "Végétation dense"];
        string[] slope = ["Plane à très faible", "Faible", "Modérée", "Forte", "Très forte"];
        var labels = theme switch
        {
            "ndvi" => ndvi,
            "slope" => slope,
            "risk" or "probability" or "forest_degradation" => fiveLevels,
            _ => [],
        };
        var level = labels.Length == count && index < labels.Length ? labels[index] + " · " : string.Empty;
        return $"{level}{Pretty(lower)} – {Pretty(upper)}";
    }

    private static string PaletteForTheme(string theme) => (theme ?? string.Empty).Trim().ToLowerInvariant() switch
    {
        "land_cover" => "Land Cover",
        "forest_dynamics" => "Forest Dynamics",
        "deforestation" => "Deforestation",
        "forest_degradation" => "Forest Degradation",
        "land_cover_change" => "Land Cover Change",
        _ => "Categorical",
    };

    private static bool IntegerLike(double value) => Math.Abs(value - Math.Round(value)) <= 1e-9;

    private static bool SameNumber(double left, double right)
        => Math.Abs(left - right) <= Math.Max(1e-12, Math.Abs(right) * 1e-12);

    private static bool ValidColor(string? value)
        => !string.IsNullOrWhiteSpace(value)
           && value.StartsWith('#')
           && value.Length is 7 or 9
           && value.Skip(1).All(character => Uri.IsHexDigit(character));

    private static string Pretty(double value)
        => IntegerLike(value)
            ? Math.Round(value).ToString("0", CultureInfo.InvariantCulture)
            : value.ToString("G8", CultureInfo.InvariantCulture);

    private static string Normalize(string? value)
    {
        var decomposed = (value ?? string.Empty).Normalize(NormalizationForm.FormD);
        var builder = new StringBuilder(decomposed.Length);
        foreach (var character in decomposed)
        {
            var category = CharUnicodeInfo.GetUnicodeCategory(character);
            if (category != UnicodeCategory.NonSpacingMark)
                builder.Append(character is '_' or '-' ? ' ' : char.ToLowerInvariant(character));
        }
        return string.Join(' ', builder.ToString().Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
    }
}
