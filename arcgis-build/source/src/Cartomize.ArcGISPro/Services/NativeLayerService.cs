using System.Globalization;
using ArcGIS.Core.Data;
using ArcGIS.Desktop.Framework.Threading.Tasks;
using ArcGIS.Desktop.Mapping;

namespace Cartomize.ArcGISPro.Services;

internal sealed record NativeFieldProfile(
    string Name,
    string TypeName,
    int SampleCount,
    int NullCount,
    int UniqueCount,
    double? Minimum,
    double? Maximum,
    string SemanticRole,
    double Confidence);

internal sealed record NativeLayerProfile(
    string LayerId,
    string Name,
    bool IsRaster,
    string GeometryType,
    string SpatialReference,
    long FeatureCount,
    int BandCount,
    int Width,
    int Height,
    string NoData,
    string Role,
    string LabelField,
    string ThematicField,
    string ThematicRole,
    string RecommendedRenderer,
    string RecommendedPalette,
    IReadOnlyList<NativeFieldProfile> Fields,
    IReadOnlyList<string> Warnings);

/// <summary>
/// Adaptation ArcGIS Pro native du profilage non destructif de
/// vector_intelligence.py et raster_intelligence.py de Cartomize QGIS 10.5.1.
/// Aucun outil Python n'est lancé par ce service.
/// </summary>
internal static class NativeLayerService
{
    private static readonly string[] LabelHints =
        ["name", "nom", "label", "libelle", "libellé", "title", "titre", "toponym"];
    private static readonly string[] IdentifierHints = ["id", "fid", "gid", "objectid", "code", "uuid"];
    private static readonly string[] CategoryHints =
        ["class", "classe", "type", "category", "categorie", "catégorie", "status", "statut", "landuse", "occupation", "zone"];
    private static readonly string[] QuantityHints =
        ["area", "surface", "ha", "population", "pop", "density", "densite", "densité", "length", "longueur", "value", "valeur"];

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
        var accumulators = fields.ToDictionary(field => field.Name, field => new FieldAccumulator(field), StringComparer.OrdinalIgnoreCase);
        var sampled = 0;
        var query = new QueryFilter
        {
            WhereClause = "1=1",
            SubFields = fields.Length == 0 ? "*" : string.Join(",", fields.Select(field => field.Name)),
        };
        using (var cursor = table.Search(query, false))
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
            }
        }

        var profiles = accumulators.Values.Select(item => item.Build()).ToArray();
        var label = profiles
            .Where(item => item.SemanticRole == "label")
            .OrderByDescending(item => item.Confidence)
            .ThenByDescending(item => item.UniqueCount)
            .Select(item => item.Name)
            .FirstOrDefault() ?? string.Empty;
        var thematic = profiles
            .Where(item => item.SemanticRole is "category" or "quantity")
            .OrderByDescending(item => item.Confidence)
            .ThenBy(item => item.UniqueCount)
            .FirstOrDefault();
        var geometry = definition is FeatureClassDefinition featureDefinition
            ? featureDefinition.GetShapeType().ToString().ToLowerInvariant()
            : "table";
        var role = InferLayerRole(layer.Name, geometry);
        var warnings = new List<string>();
        var count = table.GetCount();
        if (count > sampled)
            warnings.Add($"Profil attributaire calculé sur {sampled:N0} entités parmi {count:N0}.");
        if (string.IsNullOrWhiteSpace(label) && geometry.Contains("point", StringComparison.OrdinalIgnoreCase))
            warnings.Add("Aucun champ d’étiquette suffisamment fiable n’a été identifié.");

        return new NativeLayerProfile(
            layer.URI,
            layer.Name,
            false,
            geometry,
            layer.GetSpatialReference()?.Name ?? string.Empty,
            count,
            0,
            0,
            0,
            string.Empty,
            role,
            label,
            thematic?.Name ?? string.Empty,
            thematic?.SemanticRole ?? string.Empty,
            thematic is null ? "Symbole unique" : thematic.SemanticRole == "category" ? "Catégorisé" : "Gradué — quantiles",
            thematic?.SemanticRole == "category" ? "Qualitative" : "Séquentielle",
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
            true,
            "raster",
            layer.GetSpatialReference()?.Name ?? string.Empty,
            0,
            bandCount,
            width,
            height,
            noData,
            role,
            string.Empty,
            string.Empty,
            string.Empty,
            renderer,
            categorized ? "Categorical" : bandCount >= 3 ? "Continuous" : "Continuous",
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

    private static string InferLayerRole(string name, string geometry)
    {
        var text = name.ToLowerInvariant();
        if (text.Contains("route") || text.Contains("road") || text.Contains("rail")) return "transport";
        if (text.Contains("rivière") || text.Contains("riviere") || text.Contains("river") || text.Contains("hydro")) return "hydrographie";
        if (text.Contains("village") || text.Contains("ville") || text.Contains("city")) return "localité";
        if (text.Contains("limite") || text.Contains("admin")) return "limite";
        if (geometry.Contains("point")) return "point_thématique";
        if (geometry.Contains("line")) return "réseau";
        if (geometry.Contains("polygon")) return "zone_thématique";
        return "contexte";
    }

    private sealed class FieldAccumulator(Field field)
    {
        private readonly HashSet<string> _unique = new(StringComparer.CurrentCulture);
        private readonly List<double> _numeric = [];
        private int _count;
        private int _nullCount;

        public string Name => field.Name;

        public void Add(object? value)
        {
            _count++;
            if (value is null or DBNull)
            {
                _nullCount++;
                return;
            }
            var text = Convert.ToString(value, CultureInfo.InvariantCulture) ?? string.Empty;
            if (_unique.Count < 2000) _unique.Add(text);
            if (TryNumber(value, out var number)) _numeric.Add(number);
        }

        public NativeFieldProfile Build()
        {
            var role = InferFieldRole(Name, field.FieldType.ToString(), _unique.Count, _count - _nullCount, _numeric.Count);
            return new NativeFieldProfile(
                Name,
                field.FieldType.ToString(),
                _count,
                _nullCount,
                _unique.Count,
                _numeric.Count == 0 ? null : _numeric.Min(),
                _numeric.Count == 0 ? null : _numeric.Max(),
                role.Role,
                role.Confidence);
        }
    }

    private static (string Role, double Confidence) InferFieldRole(string name, string typeName, int uniqueCount, int validCount, int numericCount)
    {
        var text = name.ToLowerInvariant().Replace('_', ' ');
        var compact = text.Replace(" ", string.Empty);
        if (LabelHints.Any(text.Contains)) return ("label", 0.93);
        if (IdentifierHints.Contains(compact) || IdentifierHints.Any(hint => compact.EndsWith(hint, StringComparison.Ordinal)))
            return ("identifier", 0.88);
        if (CategoryHints.Any(text.Contains) || (validCount > 0 && uniqueCount is >= 2 and <= 24 && numericCount < validCount / 2))
            return ("category", 0.86);
        if (QuantityHints.Any(text.Contains) && numericCount > 0) return ("quantity", 0.9);
        if (numericCount > 0 && numericCount >= Math.Max(1, validCount * 3 / 4)) return ("quantity", 0.72);
        if (typeName.Contains("String", StringComparison.OrdinalIgnoreCase) && uniqueCount > 1) return ("text", 0.55);
        return ("other", 0.35);
    }

    private static bool TryNumber(object value, out double number)
    {
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
}
