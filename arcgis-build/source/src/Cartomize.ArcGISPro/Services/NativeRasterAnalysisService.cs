using System.Globalization;
using ArcGIS.Desktop.Framework.Threading.Tasks;
using ArcGIS.Desktop.Mapping;

namespace Cartomize.ArcGISPro.Services;

internal sealed record NativeRasterSample(
    int BandCount,
    int Width,
    int Height,
    string NoData,
    int SampleCount,
    double Minimum,
    double Maximum,
    double Mean,
    double Median,
    IReadOnlyList<double> QuantileBreaks,
    IReadOnlyDictionary<double, int> Frequencies,
    bool IsCategorical);

/// <summary>Échantillonnage non destructif des pixels par l'API Raster.</summary>
internal static class NativeRasterAnalysisService
{
    public static Task<NativeRasterSample> AnalyzeAsync(RasterLayer layer, bool deep, int classCount)
        => QueuedTask.Run(() =>
        {
            using var raster = layer.GetRaster()
                ?? throw new InvalidOperationException("Le raster sélectionné est indisponible.");
            var width = raster.GetWidth();
            var height = raster.GetHeight();
            var bandCount = NativeLayerService.GetRasterBandCount(raster, layer);
            var noDataObject = raster.GetNoDataValue();
            var noData = Convert.ToString(noDataObject, CultureInfo.InvariantCulture) ?? string.Empty;
            var hasNoData = TryNumber(noDataObject, out var noDataNumber);
            var limit = deep ? 40000 : 10000;
            var stride = Math.Max(1, (int)Math.Ceiling(Math.Sqrt((double)Math.Max(1L, (long)width * height) / limit)));
            var values = new List<double>(limit);
            var frequencies = new Dictionary<double, int>();
            for (var row = 0; row < height && values.Count < limit; row += stride)
            {
                for (var column = 0; column < width && values.Count < limit; column += stride)
                {
                    object? raw;
                    try { raw = raster.GetPixelValue(0, column, row); }
                    catch { continue; }
                    if (!TryNumber(raw, out var number) || !double.IsFinite(number)) continue;
                    if (hasNoData && Math.Abs(number - noDataNumber) <= Math.Max(1e-12, Math.Abs(noDataNumber) * 1e-12)) continue;
                    values.Add(number);
                    if (frequencies.ContainsKey(number)) frequencies[number]++;
                    else if (frequencies.Count < 512) frequencies[number] = 1;
                }
            }
            if (values.Count == 0)
                throw new InvalidOperationException("Aucun pixel numérique valide n'a pu être échantillonné.");
            values.Sort();
            var breaks = Enumerable.Range(1, Math.Clamp(classCount, 2, 12))
                .Select(index => Quantile(values, (double)index / Math.Clamp(classCount, 2, 12)))
                .ToArray();
            var categorical = frequencies.Count is >= 2 and <= 64 && frequencies.Values.Sum() == values.Count;
            return new NativeRasterSample(
                bandCount,
                width,
                height,
                noData,
                values.Count,
                values[0],
                values[^1],
                values.Average(),
                Quantile(values, 0.5),
                breaks,
                frequencies,
                categorical);
        });

    private static double Quantile(IReadOnlyList<double> values, double probability)
    {
        if (values.Count == 1) return values[0];
        var index = Math.Clamp(probability, 0, 1) * (values.Count - 1);
        var lower = (int)Math.Floor(index);
        var upper = (int)Math.Ceiling(index);
        if (lower == upper) return values[lower];
        return values[lower] + (values[upper] - values[lower]) * (index - lower);
    }

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
