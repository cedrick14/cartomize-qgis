using Cartomize.ArcGISPro.Views;

namespace Cartomize.ArcGISPro.Services;

internal sealed record NativeTemplateProjectProfile(
    string ObjectiveId,
    bool IsRaster,
    string RasterTheme,
    string RasterType,
    string PrimaryVectorRole,
    int ClassCount,
    int RasterLayerCount,
    int VectorLayerCount,
    int RelationCount);

internal sealed record NativeTemplateRecommendation(
    TemplateItem Template,
    int Score,
    double MarginPercent,
    bool AddGrid,
    string Explanation);

/// <summary>
/// Classe les maquettes à partir du résultat réel des moteurs raster et vecteur.
/// L'objectif déclaré reste un indice, mais il ne peut plus imposer une maquette
/// incohérente avec le type de couche, le nombre de classes ou la superposition.
/// </summary>
internal static class NativeTemplateRecommendationService
{
    public static IReadOnlyList<NativeTemplateRecommendation> Recommend(
        IReadOnlyList<TemplateItem> templates,
        NativeTemplateProjectProfile profile,
        int maximum = 3)
    {
        if (templates.Count == 0)
            return [];

        return templates
            .Select(template => Score(template, profile))
            .OrderByDescending(item => item.Score)
            .ThenBy(item => item.Template.TableCount + item.Template.ChartCount)
            .ThenBy(item => item.Template.Name, StringComparer.CurrentCultureIgnoreCase)
            .Take(Math.Clamp(maximum, 1, 6))
            .ToArray();
    }

    private static NativeTemplateRecommendation Score(
        TemplateItem template,
        NativeTemplateProjectProfile profile)
    {
        var score = 40;
        var reasons = new List<string>();
        var objectiveCategory = ObjectiveCategory(profile.ObjectiveId);
        if (!string.IsNullOrWhiteSpace(objectiveCategory)
            && template.Category.Equals(objectiveCategory, StringComparison.OrdinalIgnoreCase))
        {
            score += 24;
            reasons.Add("thème conforme à l’objectif");
        }

        if (template.LegendCount > 0)
            score += profile.IsRaster ? 18 : 9;
        else if (profile.IsRaster)
            score -= 80;

        if (profile.IsRaster)
            ScoreRaster(template, profile, reasons, ref score);
        else
            ScoreVector(template, profile, reasons, ref score);

        var emptyDataZones = template.ChartCount + template.TableCount;
        if (emptyDataZones > 0)
            score -= Math.Min(12, emptyDataZones * 3);

        var margin = template.PageFormat.Contains("A3", StringComparison.OrdinalIgnoreCase) ? 4d : 3d;
        var addGrid = profile.ObjectiveId is "topographique" or "atlas";
        var explanation = reasons.Count == 0
            ? "Composition polyvalente avec carte principale et légende."
            : string.Join(". ", reasons.Select(Sentence)) + ".";
        return new NativeTemplateRecommendation(
            template,
            Math.Clamp(score, 0, 99),
            margin,
            addGrid,
            explanation);
    }

    private static void ScoreRaster(
        TemplateItem template,
        NativeTemplateProjectProfile profile,
        List<string> reasons,
        ref int score)
    {
        var theme = profile.RasterTheme;
        var isChange = theme is "land_cover_change" or "forest_dynamics";
        var isForest = theme is "forest_dynamics" or "deforestation" or "forest_degradation";
        var isLandCover = theme == "land_cover" || profile.RasterType is "binary" or "categorized";

        if (isLandCover && template.Category == "occupation_sol")
        {
            score += 34;
            reasons.Add("maquette dédiée aux classes d’occupation du sol");
        }
        if (isForest && template.Category == "environnement")
        {
            score += 30;
            reasons.Add("composition adaptée à la dynamique forestière");
        }
        if (isChange && template.MapFrameCount >= 3)
        {
            score += 22;
            reasons.Add("cadres multiples adaptés à la comparaison temporelle");
        }
        if (theme is "elevation" or "slope" && template.Category == "topographique")
        {
            score += 28;
            reasons.Add("composition topographique adaptée au relief");
        }
        if (theme is "risk" or "probability" && template.Category == "humanitaire")
        {
            score += 18;
            reasons.Add("lecture prioritaire des zones de risque");
        }

        if (profile.ClassCount >= 8 && template.PageFormat.Contains("A3", StringComparison.OrdinalIgnoreCase))
        {
            score += 16;
            reasons.Add("format assez large pour une légende détaillée");
        }
        else if (profile.ClassCount is > 0 and <= 7
                 && template.PageFormat.Contains("A4", StringComparison.OrdinalIgnoreCase))
        {
            score += 10;
            reasons.Add("format compact adapté au nombre de classes");
        }

        if (!isChange && template.MapFrameCount == 2)
            score += 8;
        if (profile.RasterLayerCount > 1 && template.MapFrameCount >= 3)
            score += 8;
    }

    private static void ScoreVector(
        TemplateItem template,
        NativeTemplateProjectProfile profile,
        List<string> reasons,
        ref int score)
    {
        var complexity = profile.VectorLayerCount + profile.RelationCount;
        var inferredCategory = profile.PrimaryVectorRole switch
        {
            "transport" or "réseau" => "transport",
            "hydrographie" => "hydrologique",
            "occupation_sol" => "occupation_sol",
            "risques" => "humanitaire",
            "limites" or "localités" => "administrative",
            "bâtiments" or "parcelles" => "urbanisme",
            _ => string.Empty,
        };
        if (!string.IsNullOrWhiteSpace(inferredCategory)
            && template.Category.Equals(inferredCategory, StringComparison.OrdinalIgnoreCase))
        {
            score += 26;
            reasons.Add("maquette cohérente avec le rôle de la couche principale");
        }
        if (complexity >= 7 && template.PageFormat.Contains("A3", StringComparison.OrdinalIgnoreCase))
        {
            score += 18;
            reasons.Add("format adapté à une superposition vectorielle complexe");
        }
        if (profile.RelationCount >= 2 && template.MapFrameCount >= 3)
        {
            score += 14;
            reasons.Add("cadres complémentaires pour expliquer les relations spatiales");
        }
        if (complexity <= 4 && template.PageFormat.Contains("A4", StringComparison.OrdinalIgnoreCase))
        {
            score += 10;
            reasons.Add("composition compacte pour un projet simple");
        }
        if (profile.VectorLayerCount >= 4 && template.Category == "scientifique")
            score += 12;
    }

    private static string ObjectiveCategory(string objective) => objective switch
    {
        "occupation_sol" => "occupation_sol",
        "environnement" => "environnement",
        "transport" => "transport",
        "sante" => "sante",
        "agriculture" => "agriculture",
        "humanitaire" => "humanitaire",
        "biodiversite" => "biodiversite",
        "topographique" => "topographique",
        "administrative" => "administrative",
        _ => string.Empty,
    };

    private static string Sentence(string value)
        => value.Length == 0 ? value : char.ToUpper(value[0]) + value[1..];
}
