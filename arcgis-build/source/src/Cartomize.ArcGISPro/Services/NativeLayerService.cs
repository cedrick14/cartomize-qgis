using System.Globalization;
using ArcGIS.Core.Data;
using ArcGIS.Core.Geometry;
using ArcGIS.Desktop.Framework.Threading.Tasks;
using ArcGIS.Desktop.Mapping;

namespace Cartomize.ArcGISPro.Services;

internal sealed record NativeFieldProfile(
    string Name,
    string TypeName,
    int SampleCount,
    int NullCount,
    double NullPercent,
    int UniqueCount,
    double UniqueRatio,
    double? Minimum,
    double? Maximum,
    double? Median,
    double? Mean,
    double? Skewness,
    string SemanticRole,
    string RecommendedUse,
    double Confidence);

internal sealed record NativeLayerProfile(
    string LayerId,
    string Name,
    string Source,
    bool IsRaster,
    string GeometryType,
    string SpatialReference,
    long FeatureCount,
    int SampledFeatures,
    int InvalidGeometryCount,
    int EmptyGeometryCount,
    int MultipartCount,
    int DuplicateGeometryCount,
    int BandCount,
    int Width,
    int Height,
    string NoData,
    string Role,
    double RoleConfidence,
    string LabelField,
    string ThematicField,
    string ThematicRole,
    string RecommendedRenderer,
    string RecommendedPalette,
    IReadOnlyList<NativeFieldProfile> Fields,
    IReadOnlyList<string> Warnings);

/// <summary>
/// Portage ArcGIS Pro natif du profilage non destructif de
/// vector_intelligence.py et raster_intelligence.py de Cartomize QGIS 10.5.1.
/// </summary>
internal static class NativeLayerService
{
    private static readonly string[] NameHints =
    [
        "name", "nom", "nombre", "nome", "label", "libelle", "libellé", "title", "titre",
        "titulo", "título", "toponym", "toponimo", "topônimo",
    ];

    private static readonly string[] IdentifierHints = ["id", "fid", "gid", "objectid", "code", "uuid"];
    private static readonly string[] AreaHints =
        ["area", "área", "surface", "superf", "ha", "hectare", "hectarea", "hectárea"];
    private static readonly string[] PopulationHints =
    [
        "population", "poblacion", "población", "populacao", "população", "pop", "habit", "menage",
        "ménage", "density", "densite", "densité", "densidad", "densidade",
    ];
    private static readonly string[] ClassHints =
    [
        "class", "classe", "clase", "type", "tipo", "category", "categorie", "catégorie", "categoria",
        "status", "statut", "estado", "landuse", "occupation", "ocupacion", "ocupación", "ocupacao",
        "ocupação", "zone", "zona",
    ];
    private static readonly string[] TimeHints =
        ["year", "annee", "année", "ano", "año", "date", "data", "fecha", "time", "temps", "tempo", "mois", "month", "mes"];
    private static readonly string[] ImportanceHints =
        ["level", "niveau", "nivel", "rank", "rang", "rango", "importance", "importancia", "capital", "classe_route", "road_class", "clase_via"];

    public static Task<NativeLayerProfile> AnalyzeAsync(Layer layer, int sampleLimit = 1000)
        => QueuedTask.Run(() => layer switch
        {
            RasterLayer rasterLayer => AnalyzeRaster(rasterLayer),
            BasicFeatureLayer featureLayer => AnalyzeVector(featureLayer, Math.Clamp(sampleLimit, 100, 5000)),
            _ => throw new InvalidOperationException("Cartomize exige une couche vectorielle ou raster valide."),
        });

    private static NativeLayerProfile AnalyzeVector(BasicFeatureLayer layer, int sampleLimit)
    {
        using var table = layer.GetTable()
            ?? throw new InvalidOperationException("La table attributaire de la couche est indisponible.");
        using var definition = table.GetDefinition();
        var fields = definition.GetFields()
            .Where(field => IsProfileField(field.FieldType.ToString()))
            .Take(64)
            .ToArray();
        var accumulators = fields.ToDictionary(
            field => field.Name,
            field => new FieldAccumulator(field),
            StringComparer.OrdinalIgnoreCase);

        var sampled = 0;
        var geometryChecked = 0;
        var invalidGeometry = 0;
        var emptyGeometry = 0;
        var multipart = 0;
        var duplicateGeometry = 0;
        var seenGeometries = new HashSet<string>(StringComparer.Ordinal);
        const int geometryCheckLimit = 300;
        var query = new QueryFilter { WhereClause = "1=1", SubFields = "*" };

        using (var cursor = table.Search(query, true))
        {
            while (sampled < sampleLimit && cursor.MoveNext())
            {
                using var row = cursor.Current;
                sampled++;
                foreach (var accumulator in accumulators.Values)
                {
                    object? value;
                    try { value = row[accumulator.Name]; }
                    catch { value = null; }
                    accumulator.Add(value);
                }

                if (geometryChecked >= Math.Min(geometryCheckLimit, sampleLimit))
                    continue;
                geometryChecked++;
                try
                {
                    var shape = (row as Feature)?.GetShape();
                    if (shape is null || shape.IsEmpty)
                    {
                        emptyGeometry++;
                        continue;
                    }
                    if (shape is Multipart multipartShape && multipartShape.PartCount > 1)
                        multipart++;
                    var signature = shape.ToJson();
                    if (!seenGeometries.Add(signature))
                        duplicateGeometry++;
                    if (!GeometryEngine.Instance.IsSimpleAsFeature(shape))
                        invalidGeometry++;
                }
                catch
                {
                    emptyGeometry++;
                }
            }
        }

        var profiles = accumulators.Values.Select(item => item.Build()).ToArray();
        var label = ChooseLabelField(profiles);
        var thematic = ChooseThematicField(profiles);
        var geometry = definition is FeatureClassDefinition featureDefinition
            ? GeometryName(featureDefinition.GetShapeType().ToString())
            : "unknown";
        var source = layer.URI ?? string.Empty;
        var (role, roleConfidence) = InferLayerRole(layer.Name, source, geometry, profiles);
        var count = table.GetCount();
        var warnings = BuildVectorWarnings(
            sampled, geometryChecked, count, geometry, label,
            invalidGeometry, emptyGeometry, duplicateGeometry);
        var thematicRole = thematic?.SemanticRole ?? string.Empty;
        var renderer = RecommendedRenderer(thematicRole);
        var palette = thematicRole == "diverging_quantitative" ? "Divergente"
            : thematicRole is "category" or "coded_category" or "ordinal" ? "Qualitative"
            : "Séquentielle";

        return new NativeLayerProfile(
            layer.URI,
            layer.Name,
            source,
            false,
            geometry,
            layer.GetSpatialReference()?.Name ?? string.Empty,
            count,
            sampled,
            invalidGeometry,
            emptyGeometry,
            multipart,
            duplicateGeometry,
            0,
            0,
            0,
            string.Empty,
            role,
            roleConfidence,
            label,
            thematic?.Name ?? string.Empty,
            thematicRole,
            renderer,
            palette,
            profiles,
            warnings);
    }

    private static NativeLayerProfile AnalyzeRaster(RasterLayer layer)
    {
        using var raster = layer.GetRaster()
            ?? throw new InvalidOperationException("Le raster de la couche est indisponible.");
        var bandCount = GetRasterBandCount(raster, layer);
        var width = raster.GetWidth();
        var height = raster.GetHeight();
        var noData = raster.GetNoDataValue()?.ToString() ?? string.Empty;
        var categorized = false;
        try
        {
            using var table = raster.GetAttributeTable();
            categorized = table is not null && table.GetCount() is > 1 and <= 512;
        }
        catch
        {
            // Une table attributaire est facultative pour un raster continu.
        }
        var renderer = bandCount >= 3 ? "Composition RGB" : categorized ? "Catégoriel" : "Continu";
        var role = bandCount >= 3 ? "image" : categorized ? "raster_thématique" : "surface_continue";
        var warnings = new List<string>();
        if (!string.IsNullOrWhiteSpace(noData))
            warnings.Add($"NoData déclaré : {noData}.");

        return new NativeLayerProfile(
            layer.URI,
            layer.Name,
            layer.URI ?? string.Empty,
            true,
            "raster",
            layer.GetSpatialReference()?.Name ?? string.Empty,
            0,
            0,
            0,
            0,
            0,
            0,
            bandCount,
            width,
            height,
            noData,
            role,
            0.8,
            string.Empty,
            string.Empty,
            string.Empty,
            renderer,
            categorized ? "Categorical" : "Continuous",
            Array.Empty<NativeFieldProfile>(),
            warnings);
    }

    private static bool IsProfileField(string type)
        => !type.Contains("Geometry", StringComparison.OrdinalIgnoreCase)
           && !type.Contains("OID", StringComparison.OrdinalIgnoreCase)
           && !type.Contains("Blob", StringComparison.OrdinalIgnoreCase)
           && !type.Contains("Raster", StringComparison.OrdinalIgnoreCase)
           && !type.Contains("Xml", StringComparison.OrdinalIgnoreCase);

    internal static int GetRasterBandCount(ArcGIS.Core.Data.Raster.Raster raster, RasterLayer? layer = null)
    {
        foreach (var key in new[] { "BandCount", "bandCount", "BAND_COUNT" })
        {
            try
            {
                var value = raster.GetKeyProperty(key);
                if (value is not null && int.TryParse(Convert.ToString(value, CultureInfo.InvariantCulture), out var count) && count > 0)
                    return count;
            }
            catch
            {
                // Les fournisseurs raster n'exposent pas tous les mêmes propriétés clés.
            }
        }
        if (layer?.GetColorizer() is ArcGIS.Core.CIM.CIMRasterRGBColorizer rgb)
            return Math.Max(1, new[] { rgb.RedBandIndex, rgb.GreenBandIndex, rgb.BlueBandIndex }.Max() + 1);
        return 1;
    }

    private static IReadOnlyList<string> BuildVectorWarnings(
        int sampled,
        int geometryChecked,
        long featureCount,
        string geometry,
        string label,
        int invalid,
        int empty,
        int duplicates)
    {
        var warnings = new List<string>();
        if (invalid > 0)
            warnings.Add($"{invalid} géométrie(s) invalide(s) détectée(s) dans un échantillon de {geometryChecked}.");
        if (empty > 0)
            warnings.Add($"{empty} géométrie(s) vide(s) détectée(s) dans un échantillon de {geometryChecked}.");
        if (duplicates > 0)
            warnings.Add($"{duplicates} géométrie(s) dupliquée(s) détectée(s) dans l’échantillon contrôlé.");
        if (featureCount > sampled)
            warnings.Add($"Profil attributaire calculé sur {sampled:N0} entités parmi {featureCount:N0}.");
        if (string.IsNullOrWhiteSpace(label) && geometry == "point")
            warnings.Add("Aucun champ d’étiquette suffisamment fiable n’a été identifié.");
        return warnings;
    }

    private static string ChooseLabelField(IEnumerable<NativeFieldProfile> fields)
    {
        var candidates = fields.Where(field => field.SemanticRole == "label").ToArray();
        if (candidates.Length == 0)
            candidates = fields.Where(field => field.SemanticRole == "identifier_or_label" && field.NullPercent < 15).ToArray();
        return candidates
            .OrderByDescending(field => field.Confidence)
            .ThenBy(field => field.NullPercent)
            .ThenByDescending(field => Math.Min(field.UniqueCount, 5000))
            .Select(field => field.Name)
            .FirstOrDefault() ?? string.Empty;
    }

    private static NativeFieldProfile? ChooseThematicField(IEnumerable<NativeFieldProfile> fields)
        => fields
            .Where(field => field.SemanticRole is "category" or "coded_category" or "quantitative" or "diverging_quantitative" or "ordinal")
            .Where(field => field.NullPercent < 40 && field.UniqueCount >= 2)
            .OrderByDescending(field => field.Confidence)
            .ThenByDescending(field => field.SemanticRole is "category" or "quantitative" or "diverging_quantitative")
            .ThenBy(field => field.NullPercent)
            .FirstOrDefault();

    private static (string Role, double Confidence) InferLayerRole(
        string name,
        string source,
        string geometry,
        IEnumerable<NativeFieldProfile> fields)
    {
        var text = $"{name} {source} {string.Join(' ', fields.Select(field => field.Name))}".ToLowerInvariant();
        (string Role, string[] Tokens, double Confidence)[] rules =
        [
            ("transport", ["route", "road", "rail", "transport", "autoroute", "highway", "carretera", "estrada", "rodovia", "ferrocarril"], 0.96),
            ("hydrographie", ["rivi", "fleuve", "hydro", "water", "eau", "lac", "bassin", "rio", "río", "agua", "lago", "bacia", "cuenca"], 0.96),
            ("limites", ["limite", "boundary", "province", "district", "commune", "departement", "département", "frontera", "fronteira", "municipio", "município"], 0.95),
            ("localités", ["ville", "city", "village", "localite", "localité", "chef lieu", "town", "ciudad", "cidade", "pueblo", "localidad"], 0.94),
            ("bâtiments", ["bati", "bâti", "building", "batiment", "bâtiment", "edificio", "edifício"], 0.91),
            ("parcelles", ["parcelle", "parcel", "parcela", "cadastre", "catastro", "cadastral"], 0.91),
            ("risques", ["risque", "hazard", "alea", "aléa", "vulnerab", "flood", "inond"], 0.90),
            ("occupation_sol", ["landcover", "land cover", "lulc", "occupation", "landuse"], 0.90),
        ];
        foreach (var rule in rules)
            if (rule.Tokens.Any(text.Contains))
                return (rule.Role, rule.Confidence);
        return geometry switch
        {
            "point" => ("points_thématiques", 0.62),
            "line" => ("réseau", 0.60),
            "polygon" => ("zones_thématiques", 0.60),
            _ => ("contexte", 0.45),
        };
    }

    private static string GeometryName(string value)
    {
        var text = value.ToLowerInvariant();
        if (text.Contains("point")) return "point";
        if (text.Contains("line")) return "line";
        if (text.Contains("polygon")) return "polygon";
        return "unknown";
    }

    private static string RecommendedRenderer(string role)
        => role switch
        {
            "category" or "coded_category" or "ordinal" => "Catégorisé",
            "quantitative" or "diverging_quantitative" => "Gradué — quantiles",
            _ => "Symbole unique",
        };

    private sealed class FieldAccumulator(Field sourceField)
    {
        private readonly HashSet<string> _unique = new(StringComparer.Ordinal);
        private readonly List<double> _numeric = [];
        private int _count;
        private int _nullCount;

        public string Name => sourceField.Name;

        public void Add(object? value)
        {
            _count++;
            if (IsNull(value))
            {
                _nullCount++;
                return;
            }
            var text = $"{value!.GetType().FullName}:{Convert.ToString(value, CultureInfo.InvariantCulture)}";
            if (_unique.Count < 2000) _unique.Add(text);
            if (TryNumber(value, out var number)) _numeric.Add(number);
        }

        public NativeFieldProfile Build()
        {
            var validCount = _count - _nullCount;
            var uniqueRatio = (double)_unique.Count / Math.Max(1, validCount);
            double? minimum = _numeric.Count == 0 ? null : _numeric.Min();
            double? maximum = _numeric.Count == 0 ? null : _numeric.Max();
            var role = InferFieldRole(Name, validCount, _unique.Count, uniqueRatio, _numeric, minimum, maximum);
            return new NativeFieldProfile(
                Name,
                sourceField.FieldType.ToString(),
                _count,
                _nullCount,
                (double)_nullCount / Math.Max(1, _count) * 100.0,
                _unique.Count,
                uniqueRatio,
                minimum,
                maximum,
                _numeric.Count == 0 ? null : Median(_numeric),
                _numeric.Count == 0 ? null : _numeric.Average(),
                Skewness(_numeric),
                role.Role,
                role.Use,
                role.Confidence);
        }
    }

    private static (string Role, string Use, double Confidence) InferFieldRole(
        string name,
        int validCount,
        int uniqueCount,
        double uniqueRatio,
        IReadOnlyList<double> numeric,
        double? minimum,
        double? maximum)
    {
        var text = name.ToLowerInvariant().Replace('_', ' ');
        var compact = text.Replace(" ", string.Empty);
        var nameTokens = text.Replace('-', ' ').Split(' ', StringSplitOptions.RemoveEmptyEntries);
        if (NameHints.Any(text.Contains)) return ("label", "Étiquetage", 0.93);
        if (IdentifierHints.Contains(compact) || (nameTokens.Length > 0 && IdentifierHints.Contains(nameTokens[^1])))
            return ("identifier", "Identifiant, éviter comme variable thématique", 0.88);
        if (TimeHints.Any(text.Contains)) return ("temporal", "Filtre temporel ou série", 0.84);
        if (PopulationHints.Any(text.Contains)) return ("quantitative", "Gradué ou symbole proportionnel", numeric.Count > 0 ? 0.94 : 0.70);
        if (AreaHints.Any(text.Contains)) return ("measure", "Mesure auxiliaire", numeric.Count > 0 ? 0.86 : 0.65);
        if (ImportanceHints.Any(text.Contains)) return ("ordinal", "Hiérarchie visuelle et priorité d’étiquetage", 0.88);
        if (ClassHints.Any(text.Contains)) return ("category", "Catégories ou règles", 0.90);
        if (numeric.Count > 0 && validCount > 0)
        {
            if (uniqueCount <= 12 && uniqueRatio < 0.25) return ("coded_category", "Catégories numériques", 0.76);
            if (minimum < 0 && maximum > 0) return ("diverging_quantitative", "Gradué divergent", 0.82);
            return ("quantitative", "Gradué", 0.78);
        }
        if (uniqueCount > 0 && uniqueCount <= 25 && uniqueRatio < 0.55) return ("category", "Catégories", 0.74);
        if (uniqueRatio > 0.85) return ("identifier_or_label", "Étiquette possible, vérifier le sens", 0.58);
        return ("descriptive", "Contexte attributaire", 0.50);
    }

    private static bool IsNull(object? value)
        => value is null or DBNull
           || value is double doubleValue && !double.IsFinite(doubleValue)
           || value is float floatValue && !float.IsFinite(floatValue);

    private static bool TryNumber(object value, out double number)
    {
        if (value is bool)
        {
            number = 0;
            return false;
        }
        try
        {
            number = Convert.ToDouble(value, CultureInfo.InvariantCulture);
            return double.IsFinite(number);
        }
        catch
        {
            number = 0;
            return false;
        }
    }

    private static double Median(IEnumerable<double> values)
    {
        var ordered = values.OrderBy(value => value).ToArray();
        var middle = ordered.Length / 2;
        return ordered.Length % 2 == 0 ? (ordered[middle - 1] + ordered[middle]) / 2.0 : ordered[middle];
    }

    private static double? Skewness(IReadOnlyList<double> values)
    {
        if (values.Count < 3) return null;
        var mean = values.Average();
        var variance = values.Average(value => Math.Pow(value - mean, 2));
        if (variance <= 1e-20) return 0;
        var sigma = Math.Sqrt(variance);
        return values.Average(value => Math.Pow((value - mean) / sigma, 3));
    }
}
