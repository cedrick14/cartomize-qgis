using System.Globalization;
using ArcGIS.Desktop.Framework.Threading.Tasks;
using ArcGIS.Desktop.Mapping;

namespace Cartomize.ArcGISPro.Services;

internal sealed record NativeRasterRecommendedClass(
    double UpperBound,
    string ValueText,
    string Label,
    string Color,
    bool Visible,
    double OpacityPercent,
    long PixelCount,
    double Percentage,
    string Status);

internal sealed record NativeRasterRecommendation(
    string LayerId,
    string RenderMode,
    string Palette,
    string ClassificationMethod,
    NativeRasterSample Sample,
    IReadOnlyList<NativeRasterRecommendedClass> Classes,
    string Summary);

/// <summary>
/// Pont réutilisable entre le diagnostic Raster Engine et le panneau Projet.
/// Il garantit que les deux interfaces utilisent exactement les mêmes classes,
/// couleurs et valeurs NoData, sans repasser par le rendu raster générique.
/// </summary>
internal static class NativeRasterRecommendationService
{
    public static async Task<NativeRasterRecommendation> AnalyzeAsync(
        RasterLayer layer,
        bool deep,
        int classCount,
        string semanticContext)
    {
        var sample = await NativeRasterAnalysisService.AnalyzeAsync(
            layer,
            deep,
            classCount,
            semanticContext);
        return Build(layer.URI ?? layer.Name, sample);
    }

    public static async Task ApplyAsync(
        RasterLayer layer,
        NativeRasterRecommendation recommendation,
        int opacityPercent)
    {
        await NativeStyleService.ApplyRasterAsync(
            layer,
            new NativeRasterStyleRequest(
                recommendation.RenderMode,
                0,
                Math.Clamp(recommendation.Classes.Count(item => item.Visible), 2, 64),
                recommendation.ClassificationMethod,
                recommendation.Sample.Minimum,
                recommendation.Sample.Maximum,
                recommendation.Palette,
                recommendation.Classes.Select(item => new NativeRasterClassStyle(
                    item.UpperBound,
                    item.Label,
                    item.Color,
                    item.Visible,
                    item.OpacityPercent)).ToArray(),
                true,
                recommendation.Sample.AutomaticNoDataValues));
        await QueuedTask.Run(() => layer.SetTransparency(100 - Math.Clamp(opacityPercent, 0, 100)));

        // Le flux automatique ne dessine pas le rectangle de l'emprise raster.
        // Il retire également un ancien contour Cartomize, tandis que le fond
        // de remplissage est rendu transparent par le coloriseur ci-dessus.
        await NativeRasterOutlineService.ApplyAsync(layer, false, 1.2);
    }

    private static NativeRasterRecommendation Build(string layerId, NativeRasterSample sample)
    {
        var renderMode = sample.RasterType == "rgb"
            ? "Composition RGB"
            : sample.IsCategorical ? "Catégoriel" : "Continu";
        var palette = sample.RasterType == "rgb"
            ? "Continuous"
            : sample.IsCategorical && !string.IsNullOrWhiteSpace(sample.Nomenclature.Palette)
                ? sample.Nomenclature.Palette
                : PaletteForTheme(sample.Theme);
        var classes = sample.IsCategorical
            ? BuildCategoricalClasses(sample, palette)
            : BuildContinuousClasses(sample);
        var noData = sample.AutomaticNoDataValues.Count == 0
            ? "aucune valeur supplémentaire"
            : string.Join(", ", sample.AutomaticNoDataValues.Select(Pretty));
        var summary =
            $"Moteur : Raster Engine intelligent\n" +
            $"Type : {RasterTypeLabel(sample.RasterType)}, {sample.BandCount} bande(s)\n" +
            $"Dimensions : {sample.Width:N0} × {sample.Height:N0}\n" +
            $"Thème : {ThemeLabel(sample.Theme)}, confiance {sample.ThemeConfidence:P0}\n" +
            $"Nomenclature : {sample.Nomenclature.Name}, confiance {sample.Nomenclature.Confidence:P0}\n" +
            $"Classes visibles : {classes.Count(item => item.Visible)}\n" +
            $"NoData transparent : {noData}\n" +
            "Le rectangle de remplissage et tout ancien contour d’emprise Cartomize seront retirés à l’application.";
        return new NativeRasterRecommendation(
            layerId,
            renderMode,
            palette,
            "Quantiles de l’échantillon valide",
            sample,
            classes,
            summary);
    }

    private static IReadOnlyList<NativeRasterRecommendedClass> BuildCategoricalClasses(
        NativeRasterSample sample,
        string palette)
    {
        var result = new List<NativeRasterRecommendedClass>();
        var total = Math.Max(1, sample.Frequencies.Values.Sum());
        var proposals = sample.Nomenclature.Classes.Count > 0
            ? sample.Nomenclature.Classes
            : sample.Frequencies.OrderBy(item => item.Key)
                .Select((item, index) => new NativeRasterClassProposal(
                    item.Key,
                    $"Classe {Pretty(item.Key)}",
                    NativeStyleService.ResolvePalette(palette, sample.Frequencies.Count)[index],
                    0.60,
                    "Code détecté"))
                .ToArray();
        foreach (var proposal in proposals.Take(128))
        {
            var count = sample.Frequencies.FirstOrDefault(item => SameNumber(item.Key, proposal.Value)).Value;
            result.Add(new NativeRasterRecommendedClass(
                proposal.Value,
                Pretty(proposal.Value),
                proposal.Label,
                proposal.Color,
                true,
                100,
                count,
                100d * count / total,
                $"{proposal.Source}, confiance {proposal.Confidence:P0}"));
        }

        var allTotal = Math.Max(1, sample.AllFrequencies.Values.Sum());
        foreach (var value in sample.AutomaticNoDataValues)
        {
            var entry = sample.AllFrequencies.FirstOrDefault(item => SameNumber(item.Key, value));
            if (entry.Value <= 0 || result.Any(item => SameNumber(item.UpperBound, value))) continue;
            result.Add(new NativeRasterRecommendedClass(
                value,
                Pretty(value),
                "NoData détecté et masqué",
                "#FFFFFF",
                false,
                0,
                entry.Value,
                100d * entry.Value / allTotal,
                "Fond rectangulaire transparent"));
        }
        return result;
    }

    private static IReadOnlyList<NativeRasterRecommendedClass> BuildContinuousClasses(NativeRasterSample sample)
        => sample.ContinuousClasses.Select(range => new NativeRasterRecommendedClass(
            range.UpperBound,
            $"{Pretty(range.LowerBound)} – {Pretty(range.UpperBound)}",
            range.Label,
            range.Color,
            true,
            100,
            0,
            0,
            $"{range.Source}, confiance {range.Confidence:P0}"))
            .ToArray();

    private static string RasterTypeLabel(string value) => value switch
    {
        "binary" => "Carte binaire",
        "categorized" => "Raster catégoriel",
        "rgb" => "Image multibande RGB",
        _ => "Raster continu",
    };

    private static string ThemeLabel(string value) => value switch
    {
        "land_cover" => "Occupation du sol",
        "forest_dynamics" => "Dynamique forestière",
        "deforestation" => "Déforestation",
        "forest_degradation" => "Dégradation forestière",
        "land_cover_change" => "Changement d’occupation du sol",
        "ndvi" => "NDVI / végétation",
        "elevation" => "Altitude / MNT",
        "slope" => "Pente",
        "temperature" => "Température",
        "precipitation" => "Précipitations",
        "risk" => "Risque",
        "probability" => "Probabilité",
        "rgb" => "Image satellite",
        "categorical" => "Classification raster",
        _ => "Carte thématique continue",
    };

    private static string PaletteForTheme(string value) => value switch
    {
        "land_cover" => "Land Cover",
        "forest_dynamics" => "Forest Dynamics",
        "deforestation" => "Deforestation",
        "forest_degradation" => "Forest Degradation",
        "land_cover_change" => "Land Cover Change",
        "ndvi" => "Ndvi",
        "elevation" => "Elevation",
        "slope" => "Slope",
        "temperature" => "Temperature",
        "precipitation" => "Precipitation",
        "risk" => "Risk",
        "probability" => "Probability",
        _ => "Continuous",
    };

    private static string Pretty(double value)
        => Math.Abs(value - Math.Round(value)) <= 1e-9
            ? Math.Round(value).ToString("0", CultureInfo.InvariantCulture)
            : value.ToString("G8", CultureInfo.InvariantCulture);

    private static bool SameNumber(double left, double right)
        => Math.Abs(left - right) <= Math.Max(1e-12, Math.Abs(right) * 1e-12);
}
