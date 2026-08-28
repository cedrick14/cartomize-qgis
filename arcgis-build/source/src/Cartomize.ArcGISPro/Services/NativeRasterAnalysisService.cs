using System.Globalization;
using ArcGIS.Core.Data.Raster;
using ArcGIS.Desktop.Framework.Threading.Tasks;
using ArcGIS.Desktop.Mapping;

namespace Cartomize.ArcGISPro.Services;

internal sealed record NativeRasterCandidate(
    double Value,
    double Confidence,
    string Reason,
    double BorderPercentage,
    double CenterPercentage,
    double CornerPercentage);

internal sealed record NativeRasterSample(
    int BandCount,
    int Width,
    int Height,
    long TotalPixelCount,
    string NoData,
    int SampledPixelCount,
    int SampleCount,
    int NoDataSampleCount,
    int ObservedUniqueCount,
    bool ProfileLimited,
    double Minimum,
    double Maximum,
    double Mean,
    double Median,
    IReadOnlyList<double> QuantileBreaks,
    IReadOnlyDictionary<double, int> Frequencies,
    bool IsCategorical,
    string Theme,
    double ThemeConfidence,
    IReadOnlyList<string> ThemeRationale,
    IReadOnlyList<NativeRasterCandidate> NoDataCandidates,
    IReadOnlyList<double> AnomalousValues,
    IReadOnlyList<int> PossibleMissingCodes);

/// <summary>
/// Échantillonnage spatial non destructif par PixelBlock. Les pixels sont lus
/// en blocs répartis sur toute l'image; aucune boucle GetPixelValue n'est utilisée.
/// </summary>
internal static class NativeRasterAnalysisService
{
    private const int MaximumProfiles = 4096;

    public static Task<NativeRasterSample> AnalyzeAsync(RasterLayer layer, bool deep, int classCount)
        => QueuedTask.Run(() =>
        {
            using var raster = layer.GetRaster()
                ?? throw new InvalidOperationException("Le raster sélectionné est indisponible.");
            var width = raster.GetWidth();
            var height = raster.GetHeight();
            if (width <= 0 || height <= 0)
                throw new InvalidOperationException("Le raster sélectionné ne contient aucun pixel.");

            var bandCount = NativeLayerService.GetRasterBandCount(raster, layer);
            var noDataObject = raster.GetNoDataValue();
            var noData = Convert.ToString(noDataObject, CultureInfo.InvariantCulture) ?? string.Empty;
            var hasNoData = TryNumber(noDataObject, out var noDataNumber);
            var limit = deep ? 40000 : 10000;
            var blockWidth = Math.Min(32, width);
            var blockHeight = Math.Min(32, height);
            var blocksPerAxis = Math.Max(1, (int)Math.Ceiling(Math.Sqrt((double)limit / (blockWidth * blockHeight))));
            var columns = SampleOrigins(width, blockWidth, blocksPerAxis);
            var rows = SampleOrigins(height, blockHeight, blocksPerAxis);

            var values = new List<double>(limit);
            var frequencies = new Dictionary<double, int>();
            var borderFrequencies = new Dictionary<double, int>();
            var centerFrequencies = new Dictionary<double, int>();
            var cornerFrequencies = new Dictionary<double, int>();
            var borderTotal = 0;
            var centerTotal = 0;
            var cornerTotal = 0;
            var sampledPixels = 0;
            var noDataPixels = 0;
            var profileLimited = false;

            for (var rowIndex = 0; rowIndex < rows.Count && values.Count < limit; rowIndex++)
            {
                for (var columnIndex = 0; columnIndex < columns.Count && values.Count < limit; columnIndex++)
                {
                    var x = columns[columnIndex];
                    var y = rows[rowIndex];
                    var isBorderBlock = rowIndex == 0 || columnIndex == 0 || rowIndex == rows.Count - 1 || columnIndex == columns.Count - 1;
                    var isCornerBlock = (rowIndex == 0 || rowIndex == rows.Count - 1)
                                        && (columnIndex == 0 || columnIndex == columns.Count - 1);
                    var isCenterBlock = !isBorderBlock;
                    using var pixelBlock = raster.CreatePixelBlock(blockWidth, blockHeight);
                    raster.Read(x, y, pixelBlock);
                    if (pixelBlock.GetPlaneCount() == 0)
                        continue;
                    var pixels = pixelBlock.GetPixelData(0, true);
                    for (var pixelRow = 0; pixelRow < pixelBlock.GetHeight() && values.Count < limit; pixelRow++)
                    {
                        for (var pixelColumn = 0; pixelColumn < pixelBlock.GetWidth() && values.Count < limit; pixelColumn++)
                        {
                            sampledPixels++;
                            if (Convert.ToByte(pixelBlock.GetNoDataMaskValue(0, pixelColumn, pixelRow), CultureInfo.InvariantCulture) != 1)
                            {
                                noDataPixels++;
                                continue;
                            }
                            var raw = pixels.GetValue(pixelColumn, pixelRow);
                            if (!TryNumber(raw, out var number)
                                || !double.IsFinite(number)
                                || hasNoData && SameNumber(number, noDataNumber))
                            {
                                noDataPixels++;
                                continue;
                            }
                            values.Add(number);
                            AddFrequency(frequencies, number, ref profileLimited);
                            if (isBorderBlock)
                            {
                                borderTotal++;
                                AddFrequency(borderFrequencies, number, ref profileLimited);
                            }
                            if (isCenterBlock)
                            {
                                centerTotal++;
                                AddFrequency(centerFrequencies, number, ref profileLimited);
                            }
                            if (isCornerBlock)
                            {
                                cornerTotal++;
                                AddFrequency(cornerFrequencies, number, ref profileLimited);
                            }
                        }
                    }
                }
            }

            if (values.Count == 0)
                throw new InvalidOperationException("Aucun pixel numérique valide n'a pu être échantillonné.");

            values.Sort();
            var classes = Math.Clamp(classCount, 2, 12);
            var breaks = Enumerable.Range(1, classes)
                .Select(index => Quantile(values, (double)index / classes))
                .ToArray();
            var observedUnique = frequencies.Count;
            var categorical = !profileLimited && observedUnique is >= 2 and <= 64;
            var candidates = DetectNoDataCandidates(
                hasNoData ? noDataNumber : null,
                frequencies,
                borderFrequencies,
                centerFrequencies,
                cornerFrequencies,
                borderTotal,
                centerTotal,
                cornerTotal);
            var anomalies = DetectAnomalies(values, candidates.Select(candidate => candidate.Value));
            var missingCodes = DetectMissingCodes(frequencies.Keys, categorical);
            var (theme, themeConfidence, rationale) = InferTheme(layer.Name, bandCount, categorical, values[0], values[^1]);

            return new NativeRasterSample(
                bandCount,
                width,
                height,
                (long)width * height,
                noData,
                sampledPixels,
                values.Count,
                noDataPixels,
                observedUnique,
                profileLimited,
                values[0],
                values[^1],
                values.Average(),
                Quantile(values, 0.5),
                breaks,
                frequencies,
                categorical,
                theme,
                themeConfidence,
                rationale,
                candidates,
                anomalies,
                missingCodes);
        });

    private static IReadOnlyList<int> SampleOrigins(int dimension, int blockSize, int count)
    {
        var maximum = Math.Max(0, dimension - blockSize);
        if (count <= 1 || maximum == 0) return [0];
        return Enumerable.Range(0, count)
            .Select(index => (int)Math.Round((double)index * maximum / (count - 1)))
            .Distinct()
            .ToArray();
    }

    private static void AddFrequency(IDictionary<double, int> target, double value, ref bool limited)
    {
        if (target.TryGetValue(value, out var count))
        {
            target[value] = count + 1;
            return;
        }
        if (target.Count < MaximumProfiles)
            target[value] = 1;
        else
            limited = true;
    }

    private static IReadOnlyList<NativeRasterCandidate> DetectNoDataCandidates(
        double? sourceNoData,
        IReadOnlyDictionary<double, int> frequencies,
        IReadOnlyDictionary<double, int> border,
        IReadOnlyDictionary<double, int> center,
        IReadOnlyDictionary<double, int> corners,
        int borderTotal,
        int centerTotal,
        int cornerTotal)
    {
        var candidates = new Dictionary<double, NativeRasterCandidate>();
        if (sourceNoData is double declared && double.IsFinite(declared))
            candidates[declared] = new NativeRasterCandidate(
                declared, 0.995, "Valeur NoData déclarée par le fournisseur raster.", 0, 0, 0);

        foreach (var value in frequencies.Keys)
        {
            var borderPercentage = border.GetValueOrDefault(value) / (double)Math.Max(1, borderTotal);
            var centerPercentage = center.GetValueOrDefault(value) / (double)Math.Max(1, centerTotal);
            var cornerPercentage = corners.GetValueOrDefault(value) / (double)Math.Max(1, cornerTotal);
            var borderSignal = borderPercentage - centerPercentage;
            var strongPerimeter = borderPercentage >= 0.60 && centerPercentage <= 0.45 && borderSignal >= 0.35;
            var strongCorners = cornerPercentage >= 0.75 && borderPercentage >= 0.50
                                && centerPercentage <= 0.60 && borderSignal >= 0.20;
            if (!strongPerimeter && !strongCorners) continue;
            var spatialSignal = Math.Max(borderSignal, cornerPercentage - centerPercentage);
            var confidence = Math.Clamp(0.58 + spatialSignal * 0.42, 0, 0.98);
            var candidate = new NativeRasterCandidate(
                value,
                Math.Round(confidence, 4),
                "Valeur très concentrée en bordure du raster et rare au centre.",
                borderPercentage,
                centerPercentage,
                cornerPercentage);
            if (!candidates.TryGetValue(value, out var existing) || candidate.Confidence > existing.Confidence)
                candidates[value] = candidate;
        }
        return candidates.Values.OrderByDescending(candidate => candidate.Confidence).ThenBy(candidate => candidate.Value).ToArray();
    }

    private static IReadOnlyList<double> DetectAnomalies(IReadOnlyList<double> sortedValues, IEnumerable<double> noDataValues)
    {
        if (sortedValues.Count < 20) return [];
        var excluded = noDataValues.ToHashSet();
        var q1 = Quantile(sortedValues, 0.25);
        var q3 = Quantile(sortedValues, 0.75);
        var spread = q3 - q1;
        if (spread <= 0) return [];
        var lower = q1 - 3 * spread;
        var upper = q3 + 3 * spread;
        return sortedValues
            .Where(value => !excluded.Contains(value) && (value < lower || value > upper))
            .Distinct()
            .Take(20)
            .ToArray();
    }

    private static IReadOnlyList<int> DetectMissingCodes(IEnumerable<double> values, bool categorical)
    {
        if (!categorical) return [];
        var codes = values
            .Where(value => Math.Abs(value - Math.Round(value)) <= 1e-9)
            .Select(value => (int)Math.Round(value))
            .Distinct()
            .OrderBy(value => value)
            .ToArray();
        if (codes.Length is < 2 or > 128 || (long)codes[^1] - codes[0] > 512) return [];
        var present = codes.ToHashSet();
        return Enumerable.Range(codes[0], codes[^1] - codes[0] + 1)
            .Where(value => !present.Contains(value))
            .Take(64)
            .ToArray();
    }

    private static (string Theme, double Confidence, IReadOnlyList<string> Rationale) InferTheme(
        string layerName,
        int bandCount,
        bool categorical,
        double minimum,
        double maximum)
    {
        var text = (layerName ?? string.Empty).ToLowerInvariant();
        (string Theme, string[] Tokens, double Confidence)[] rules =
        [
            ("deforestation", ["deforest", "déforest"], 0.96),
            ("forest_degradation", ["degrad", "dégrad"], 0.94),
            ("forest_dynamics", ["forest", "forêt", "couvert végétal", "couvert_vegetal"], 0.90),
            ("ndvi", ["ndvi", "vegetation", "végétation"], 0.97),
            ("elevation", ["dem", "mnt", "elevation", "élévation", "altitude"], 0.96),
            ("slope", ["slope", "pente"], 0.96),
            ("temperature", ["temperature", "température", "lst"], 0.95),
            ("precipitation", ["precip", "précip", "rain", "pluie"], 0.94),
            ("risk", ["risk", "risque", "hazard", "aléa"], 0.93),
            ("probability", ["probability", "probabilité", "probabilite"], 0.93),
            ("land_cover", ["landcover", "land cover", "occupation", "lulc"], 0.93),
        ];
        foreach (var rule in rules)
            if (rule.Tokens.Any(text.Contains))
                return (rule.Theme, rule.Confidence, [$"Nom de couche compatible avec le thème {rule.Theme}."]);
        if (bandCount >= 3)
            return ("rgb", 0.62, ["Le raster contient au moins trois bandes, sans métadonnée thématique décisive."]);
        if (categorical)
            return ("categorical", 0.60, ["Les valeurs sont discrètes; les libellés métier doivent être confirmés."]);
        if (minimum >= -1.05 && maximum <= 1.05)
            return ("continuous", 0.58, ["La plage observée est compatible avec un indice normalisé, sans le prouver."]);
        return ("continuous", 0.60, ["Aucun thème spécialisé n’est suffisamment étayé."]);
    }

    private static double Quantile(IReadOnlyList<double> values, double probability)
    {
        if (values.Count == 1) return values[0];
        var index = Math.Clamp(probability, 0, 1) * (values.Count - 1);
        var lower = (int)Math.Floor(index);
        var upper = (int)Math.Ceiling(index);
        if (lower == upper) return values[lower];
        return values[lower] + (values[upper] - values[lower]) * (index - lower);
    }

    private static bool SameNumber(double left, double right)
        => Math.Abs(left - right) <= Math.Max(1e-12, Math.Abs(right) * 1e-12);

    private static bool TryNumber(object? value, out double number)
    {
        try
        {
            if (value is Array array && array.Length > 0) value = array.GetValue(0);
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
