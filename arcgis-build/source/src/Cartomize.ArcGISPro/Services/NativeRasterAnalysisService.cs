using System.Globalization;
using ArcGIS.Core.Data;
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
    IReadOnlyDictionary<double, int> AllFrequencies,
    IReadOnlyDictionary<double, int> Frequencies,
    IReadOnlyDictionary<double, double> BorderPercentages,
    bool IsCategorical,
    string RasterType,
    string Theme,
    double ThemeConfidence,
    IReadOnlyList<string> ThemeRationale,
    NativeRasterNomenclature Nomenclature,
    IReadOnlyList<NativeRasterRangeProposal> ContinuousClasses,
    IReadOnlyList<double> AutomaticNoDataValues,
    bool HasRasterAttributeTable,
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
            var attributeClasses = ReadAttributeClasses(raster);
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

            var candidates = DetectNoDataCandidates(
                hasNoData ? noDataNumber : null,
                frequencies,
                borderFrequencies,
                centerFrequencies,
                cornerFrequencies,
                borderTotal,
                centerTotal,
                cornerTotal);
            var automaticNoData = SelectAutomaticNoDataValues(
                hasNoData ? noDataNumber : null,
                bandCount,
                frequencies,
                candidates);
            var automaticSet = automaticNoData.ToHashSet();
            var validValues = values.Where(value => !automaticSet.Any(candidate => SameNumber(candidate, value))).ToList();
            if (validValues.Count == 0)
                throw new InvalidOperationException("Toutes les valeurs échantillonnées correspondent au NoData détecté.");
            validValues.Sort();
            var validFrequencies = frequencies
                .Where(item => !automaticSet.Any(candidate => SameNumber(candidate, item.Key)))
                .ToDictionary(item => item.Key, item => item.Value);
            var observedUnique = validFrequencies.Count;
            var integerCodes = validFrequencies.Keys.All(IntegerLike);
            var categorical = bandCount == 1
                              && !profileLimited
                              && observedUnique is >= 2 and <= 128
                              && (integerCodes || attributeClasses.Count > 1);
            var rasterType = bandCount >= 3 && !categorical
                ? "rgb"
                : categorical && observedUnique == 2
                    ? "binary"
                    : categorical ? "categorized" : "continuous";
            var classes = Math.Clamp(classCount, 2, 12);
            var breaks = Enumerable.Range(1, classes)
                .Select(index => Quantile(validValues, (double)index / classes))
                .Distinct()
                .ToArray();
            var context = string.Join(" ", new[]
            {
                layer.Name,
                layer.URI ?? string.Empty,
                string.Join(" ", attributeClasses.Select(item => item.Label)),
            });
            var (theme, themeConfidence, rationale) = InferTheme(
                context,
                bandCount,
                rasterType,
                validValues[0],
                validValues[^1]);
            var nomenclature = categorical
                ? NativeRasterNomenclatureService.ProposeCategorical(
                    context,
                    rasterType,
                    theme,
                    validFrequencies.Keys.ToArray(),
                    attributeClasses)
                : new NativeRasterNomenclature(
                    rasterType,
                    rasterType == "rgb" ? "Composition multibande" : "Classes continues",
                    theme,
                    theme,
                    themeConfidence,
                    rationale,
                    []);
            if (!string.IsNullOrWhiteSpace(nomenclature.Theme)
                && nomenclature.Theme != "categorical"
                && nomenclature.Confidence > themeConfidence)
            {
                theme = nomenclature.Theme;
                themeConfidence = nomenclature.Confidence;
                rationale = rationale.Concat(nomenclature.Rationale).Distinct().ToArray();
            }
            var continuousClasses = rasterType == "continuous"
                ? NativeRasterNomenclatureService.ProposeContinuous(theme, validValues[0], validValues[^1], breaks)
                : [];
            var anomalies = DetectAnomalies(validValues, automaticNoData);
            var missingCodes = DetectMissingCodes(validFrequencies.Keys, categorical);
            var borderPercentages = frequencies.Keys.ToDictionary(
                value => value,
                value => 100d * borderFrequencies.GetValueOrDefault(value) / Math.Max(1, borderTotal));
            var automaticallyMaskedSamples = frequencies
                .Where(item => automaticSet.Any(candidate => SameNumber(candidate, item.Key)))
                .Sum(item => item.Value);

            return new NativeRasterSample(
                bandCount,
                width,
                height,
                (long)width * height,
                noData,
                sampledPixels,
                values.Count,
                noDataPixels + automaticallyMaskedSamples,
                observedUnique,
                profileLimited,
                validValues[0],
                validValues[^1],
                validValues.Average(),
                Quantile(validValues, 0.5),
                breaks,
                new Dictionary<double, int>(frequencies),
                validFrequencies,
                borderPercentages,
                categorical,
                rasterType,
                theme,
                themeConfidence,
                rationale,
                nomenclature,
                continuousClasses,
                automaticNoData,
                attributeClasses.Count > 0,
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

    private static IReadOnlyList<double> SelectAutomaticNoDataValues(
        double? sourceNoData,
        int bandCount,
        IReadOnlyDictionary<double, int> frequencies,
        IReadOnlyList<NativeRasterCandidate> candidates)
    {
        var selected = new HashSet<double>();
        if (sourceNoData is double declared && double.IsFinite(declared))
            selected.Add(declared);

        var categoricalShape = bandCount == 1
                               && frequencies.Count is >= 2 and <= 65
                               && frequencies.Keys.All(IntegerLike);
        if (!categoricalShape) return selected.OrderBy(value => value).ToArray();

        foreach (var candidate in candidates)
        {
            if (sourceNoData is double source && SameNumber(source, candidate.Value)) continue;
            var borderSignal = candidate.BorderPercentage - candidate.CenterPercentage;
            var strongPerimeter = candidate.Confidence >= 0.78
                                  && candidate.BorderPercentage >= 0.65
                                  && candidate.CenterPercentage <= 0.38
                                  && borderSignal >= 0.42;
            var strongCorners = candidate.Confidence >= 0.78
                                && candidate.CornerPercentage >= 0.85
                                && candidate.BorderPercentage >= 0.55
                                && candidate.CenterPercentage <= 0.55
                                && borderSignal >= 0.25;
            if (strongPerimeter || strongCorners)
                selected.Add(candidate.Value);
        }
        return selected.OrderBy(value => value).ToArray();
    }

    private static IReadOnlyList<NativeRasterAttributeClass> ReadAttributeClasses(Raster raster)
    {
        try
        {
            using var table = raster.GetAttributeTable();
            if (table is null) return [];
            using var definition = table.GetDefinition();
            var fields = definition.GetFields().ToArray();
            if (fields.Length == 0) return [];

            static string FieldKey(string value)
                => new(value.Where(char.IsLetterOrDigit).Select(char.ToLowerInvariant).ToArray());
            var valueNames = new HashSet<string>(
                ["value", "classvalue", "code", "gridcode", "classcode", "classecode"],
                StringComparer.OrdinalIgnoreCase);
            var labelNames = new HashSet<string>(
                ["classname", "class", "classe", "label", "libelle", "nom", "name", "description", "category", "categorie", "landcover"],
                StringComparer.OrdinalIgnoreCase);
            var valueField = fields.FirstOrDefault(field => valueNames.Contains(FieldKey(field.Name)))
                             ?? fields.FirstOrDefault(field =>
                                 IsNumericField(field.FieldType.ToString())
                                 && !FieldKey(field.Name).Contains("count", StringComparison.Ordinal));
            if (valueField is null) return [];
            var labelField = fields.FirstOrDefault(field =>
                labelNames.Contains(FieldKey(field.Name))
                && !field.Name.Equals(valueField.Name, StringComparison.OrdinalIgnoreCase));
            var colorField = fields.FirstOrDefault(field =>
                FieldKey(field.Name) is "color" or "colour" or "hex" or "rgb");
            var redField = fields.FirstOrDefault(field => FieldKey(field.Name) is "red" or "rouge");
            var greenField = fields.FirstOrDefault(field => FieldKey(field.Name) is "green" or "vert");
            var blueField = fields.FirstOrDefault(field => FieldKey(field.Name) is "blue" or "bleu");
            var result = new List<NativeRasterAttributeClass>();
            using var cursor = table.Search(new QueryFilter { WhereClause = "1=1", SubFields = "*" }, true);
            while (result.Count < 512 && cursor.MoveNext())
            {
                using var row = cursor.Current;
                if (!TryNumber(ReadRow(row, valueField.Name), out var value)) continue;
                var label = Convert.ToString(
                    labelField is null ? null : ReadRow(row, labelField.Name),
                    CultureInfo.CurrentCulture)?.Trim() ?? string.Empty;
                var color = NormalizeColor(colorField is null ? null : ReadRow(row, colorField.Name));
                if (string.IsNullOrWhiteSpace(color)
                    && TryByte(redField is null ? null : ReadRow(row, redField.Name), out var red)
                    && TryByte(greenField is null ? null : ReadRow(row, greenField.Name), out var green)
                    && TryByte(blueField is null ? null : ReadRow(row, blueField.Name), out var blue))
                    color = $"#{red:X2}{green:X2}{blue:X2}";
                result.Add(new NativeRasterAttributeClass(value, label, color));
            }
            return result
                .GroupBy(item => item.Value)
                .Select(group => group.First())
                .OrderBy(item => item.Value)
                .ToArray();
        }
        catch
        {
            // Une table attributaire raster est facultative et parfois virtuelle.
            return [];
        }
    }

    private static object? ReadRow(Row row, string field)
    {
        try { return row[field]; }
        catch { return null; }
    }

    private static bool IsNumericField(string fieldType)
        => fieldType.Contains("Integer", StringComparison.OrdinalIgnoreCase)
           || fieldType.Contains("Single", StringComparison.OrdinalIgnoreCase)
           || fieldType.Contains("Double", StringComparison.OrdinalIgnoreCase)
           || fieldType.Contains("Float", StringComparison.OrdinalIgnoreCase)
           || fieldType.Contains("Decimal", StringComparison.OrdinalIgnoreCase);

    private static bool TryByte(object? value, out byte number)
    {
        if (TryNumber(value, out var parsed) && parsed is >= 0 and <= 255)
        {
            number = (byte)Math.Round(parsed);
            return true;
        }
        number = 0;
        return false;
    }

    private static string NormalizeColor(object? value)
    {
        var text = Convert.ToString(value, CultureInfo.InvariantCulture)?.Trim() ?? string.Empty;
        if (text.Length == 6 && text.All(Uri.IsHexDigit)) text = "#" + text;
        return text.Length is 7 or 9
               && text.StartsWith('#')
               && text.Skip(1).All(Uri.IsHexDigit)
            ? text.ToUpperInvariant()
            : string.Empty;
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
        string context,
        int bandCount,
        string rasterType,
        double minimum,
        double maximum)
    {
        var text = (context ?? string.Empty).ToLowerInvariant();
        (string Theme, string[] Tokens, double Confidence)[] rules =
        [
            ("land_cover_change", ["land cover change", "changement occupation", "transition occupation"], 0.96),
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
                return (rule.Theme, rule.Confidence, [$"Le nom, le chemin ou les libellés du raster concordent avec le thème {rule.Theme}."]);
        if (rasterType == "rgb" || bandCount >= 3)
            return ("rgb", 0.62, ["Le raster contient au moins trois bandes, sans métadonnée thématique décisive."]);
        if (rasterType is "binary" or "categorized")
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

    private static bool IntegerLike(double value)
        => Math.Abs(value - Math.Round(value)) <= 1e-9;

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
