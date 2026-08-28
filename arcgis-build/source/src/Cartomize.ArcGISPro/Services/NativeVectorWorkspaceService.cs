using ArcGIS.Core.CIM;
using ArcGIS.Core.Data;
using ArcGIS.Core.Geometry;
using ArcGIS.Desktop.Framework.Threading.Tasks;
using ArcGIS.Desktop.Mapping;

namespace Cartomize.ArcGISPro.Services;

internal sealed record NativeVectorLayerDescriptor(
    string LayerId,
    string Name,
    string GeometryType,
    bool IsVisible,
    bool IsTopLevel);

internal sealed record NativeVectorRelation(
    string LeftLayerId,
    string LeftLayerName,
    string RightLayerId,
    string RightLayerName,
    string Relation,
    string SuggestedOperation,
    string ExpectedResult,
    double ExtentOverlapPercent,
    int SampledFeatures,
    int IntersectingFeatures,
    bool SpatialReferenceMismatch,
    double Confidence,
    string Evidence);

public sealed record NativeVectorCompositionItem(
    string LayerId,
    string LayerName,
    string GeometryType,
    string Role,
    int OrderIndex,
    int OpacityPercent,
    bool EnableLabels,
    string Renderer,
    string Palette,
    string Reason);

internal sealed record NativeVectorOperation(
    int Order,
    string Name,
    string InputLayers,
    string Method,
    string Output,
    bool Automatic,
    double Confidence,
    string Reason);

internal sealed record NativeVectorWorkspaceAnalysis(
    string MapName,
    string Objective,
    string PrimaryLayerId,
    IReadOnlyList<NativeLayerProfile> Profiles,
    IReadOnlyList<NativeVectorRelation> Relations,
    IReadOnlyList<NativeVectorCompositionItem> Composition,
    IReadOnlyList<NativeVectorOperation> Operations,
    IReadOnlyList<string> Warnings,
    string Summary,
    string PlanText);

internal sealed record NativeVectorCompositionSnapshot(
    IReadOnlyDictionary<string, CIMBaseLayer> LayerDefinitions,
    IReadOnlyList<string> RootLayerOrder);

/// <summary>
/// Analyse plusieurs couches vectorielles comme un système : rôles, qualité,
/// recouvrements, relations topologiques échantillonnées et ordre de dessin.
/// Le service ne modifie jamais les entités sources. Les seules mutations
/// possibles sont la symbologie et l'ordre des couches, toutes réversibles.
/// </summary>
internal static class NativeVectorWorkspaceService
{
    private const int MaximumAnalyzedLayers = 32;

    public static Task<IReadOnlyList<NativeVectorLayerDescriptor>> InventoryAsync(Map map)
        => QueuedTask.Run<IReadOnlyList<NativeVectorLayerDescriptor>>(() =>
            map.GetLayersAsFlattenedList()
                .OfType<BasicFeatureLayer>()
                .Select(layer => new NativeVectorLayerDescriptor(
                    layer.URI ?? layer.Name,
                    layer.Name,
                    GeometryType(layer),
                    layer.IsVisible,
                    map.Layers.Contains(layer)))
                .ToArray());

    public static Task<NativeVectorWorkspaceAnalysis> AnalyzeAsync(
        Map map,
        IReadOnlyCollection<string> requestedLayerIds,
        string primaryLayerId,
        string objective,
        bool visibleOnly,
        bool deep)
        => QueuedTask.Run(() =>
        {
            var requested = requestedLayerIds.ToHashSet(StringComparer.Ordinal);
            var allLayers = map.GetLayersAsFlattenedList()
                .OfType<BasicFeatureLayer>()
                .Where(layer => requested.Count == 0 || requested.Contains(layer.URI ?? layer.Name))
                .Where(layer => !visibleOnly || layer.IsVisible)
                .ToArray();
            if (allLayers.Length == 0)
                throw new InvalidOperationException("Aucune couche vectorielle n'est disponible pour l'analyse multi-couches.");

            var warnings = new List<string>();
            var layers = allLayers
                .OrderByDescending(layer => string.Equals(layer.URI ?? layer.Name, primaryLayerId, StringComparison.Ordinal))
                .ThenByDescending(layer => layer.IsVisible)
                .Take(MaximumAnalyzedLayers)
                .ToArray();
            if (allLayers.Length > layers.Length)
                warnings.Add($"{allLayers.Length - layers.Length} couche(s) supplémentaire(s) ignorée(s) pour maintenir une analyse interactive.");

            var sampleLimit = deep ? 2500 : 600;
            var profiles = layers
                .Select(layer => NativeLayerService.AnalyzeVectorOnWorker(layer, sampleLimit))
                .ToArray();
            var profileById = profiles.ToDictionary(profile => profile.LayerId, StringComparer.Ordinal);
            var extents = layers.ToDictionary(
                layer => layer.URI ?? layer.Name,
                layer => SafeExtent(layer),
                StringComparer.Ordinal);

            var relations = new List<NativeVectorRelation>();
            var spatialSampleLimit = deep ? 80 : 24;
            for (var leftIndex = 0; leftIndex < layers.Length; leftIndex++)
            {
                for (var rightIndex = leftIndex + 1; rightIndex < layers.Length; rightIndex++)
                {
                    var left = layers[leftIndex];
                    var right = layers[rightIndex];
                    var leftId = left.URI ?? left.Name;
                    var rightId = right.URI ?? right.Name;
                    relations.Add(AnalyzeRelation(
                        left,
                        right,
                        profileById[leftId],
                        profileById[rightId],
                        extents[leftId],
                        extents[rightId],
                        spatialSampleLimit));
                }
            }

            var resolvedPrimary = profiles.Any(profile => profile.LayerId.Equals(primaryLayerId, StringComparison.Ordinal))
                ? primaryLayerId
                : profiles[0].LayerId;
            var composition = BuildComposition(profiles, resolvedPrimary);
            var operations = BuildOperationPlan(relations, profiles, resolvedPrimary, objective);
            warnings.AddRange(BuildWorkspaceWarnings(profiles, relations));
            var summary = BuildSummary(map.Name, profiles, relations, operations, warnings, deep);
            var planText = BuildPlanText(objective, resolvedPrimary, profiles, composition, operations, warnings);
            return new NativeVectorWorkspaceAnalysis(
                map.Name,
                objective,
                resolvedPrimary,
                profiles,
                relations,
                composition,
                operations,
                warnings.Distinct(StringComparer.CurrentCultureIgnoreCase).ToArray(),
                summary,
                planText);
        });

    public static Task<NativeVectorCompositionSnapshot> CaptureCompositionAsync(
        Map map,
        IReadOnlyCollection<string> layerIds)
        => QueuedTask.Run(() =>
        {
            var ids = layerIds.ToHashSet(StringComparer.Ordinal);
            var definitions = map.GetLayersAsFlattenedList()
                .Where(layer => ids.Contains(layer.URI ?? layer.Name))
                .ToDictionary(
                    layer => layer.URI ?? layer.Name,
                    layer => layer.GetDefinition(),
                    StringComparer.Ordinal);
            var order = map.Layers.Select(layer => layer.URI ?? layer.Name).ToArray();
            return new NativeVectorCompositionSnapshot(definitions, order);
        });

    public static Task ApplyCompositionAsync(
        Map map,
        NativeVectorWorkspaceAnalysis analysis,
        bool reorderLayers,
        bool harmonizeStyles,
        bool enableLabels)
        => QueuedTask.Run(() =>
        {
            var layers = map.GetLayersAsFlattenedList()
                .OfType<BasicFeatureLayer>()
                .ToDictionary(layer => layer.URI ?? layer.Name, StringComparer.Ordinal);
            var profiles = analysis.Profiles.ToDictionary(profile => profile.LayerId, StringComparer.Ordinal);

            if (harmonizeStyles)
            {
                foreach (var item in analysis.Composition)
                {
                    if (!layers.TryGetValue(item.LayerId, out var layer)
                        || !profiles.TryGetValue(item.LayerId, out var profile))
                        continue;
                    NativeStyleService.ApplyVectorProfileOnWorker(
                        layer,
                        profile,
                        item.OpacityPercent,
                        enableLabels && item.EnableLabels);
                }
            }

            if (!reorderLayers)
                return;
            var position = 0;
            foreach (var item in analysis.Composition.OrderBy(item => item.OrderIndex))
            {
                if (!layers.TryGetValue(item.LayerId, out var layer) || !map.Layers.Contains(layer))
                    continue;
                map.MoveLayer(layer, position++);
            }
        });

    public static Task RestoreCompositionAsync(Map map, NativeVectorCompositionSnapshot snapshot)
        => QueuedTask.Run(() =>
        {
            var layers = map.GetLayersAsFlattenedList()
                .ToDictionary(layer => layer.URI ?? layer.Name, StringComparer.Ordinal);
            foreach (var pair in snapshot.LayerDefinitions)
                if (layers.TryGetValue(pair.Key, out var layer))
                    layer.SetDefinition(pair.Value);

            for (var position = 0; position < snapshot.RootLayerOrder.Count; position++)
            {
                if (!layers.TryGetValue(snapshot.RootLayerOrder[position], out var layer)
                    || !map.Layers.Contains(layer))
                    continue;
                map.MoveLayer(layer, position);
            }
        });

    private static NativeVectorRelation AnalyzeRelation(
        BasicFeatureLayer left,
        BasicFeatureLayer right,
        NativeLayerProfile leftProfile,
        NativeLayerProfile rightProfile,
        Envelope? leftExtent,
        Envelope? rightExtent,
        int sampleLimit)
    {
        var overlap = ExtentOverlapPercent(leftExtent, rightExtent);
        var crsMismatch = !string.IsNullOrWhiteSpace(leftProfile.SpatialReference)
                          && !string.IsNullOrWhiteSpace(rightProfile.SpatialReference)
                          && !leftProfile.SpatialReference.Equals(rightProfile.SpatialReference, StringComparison.OrdinalIgnoreCase);
        var (relation, operation, output) = RelationRule(
            leftProfile.GeometryType,
            rightProfile.GeometryType,
            overlap);
        var sampled = 0;
        var intersecting = 0;
        if (overlap > 0)
            (sampled, intersecting) = CountSpatialIntersections(left, right, sampleLimit);

        if (overlap > 0 && sampled > 0 && intersecting == 0)
            relation = "Emprises superposées, croisement non confirmé dans l'échantillon";
        var confidence = intersecting > 0 ? 0.94 : overlap <= 0 ? 0.82 : sampled > 0 ? 0.68 : 0.60;
        if (crsMismatch) confidence -= 0.12;
        var evidence = overlap <= 0
            ? "Les emprises ne se recouvrent pas ; une analyse de proximité reste possible."
            : sampled == 0
                ? $"Recouvrement d'emprise : {overlap:0.##} %."
                : $"{intersecting}/{sampled} entité(s) échantillonnée(s) intersectent l'autre couche ; recouvrement d'emprise {overlap:0.##} %.";
        return new NativeVectorRelation(
            leftProfile.LayerId,
            leftProfile.Name,
            rightProfile.LayerId,
            rightProfile.Name,
            relation,
            operation,
            output,
            overlap,
            sampled,
            intersecting,
            crsMismatch,
            Math.Clamp(confidence, 0.35, 0.99),
            evidence);
    }

    private static (int Sampled, int Intersecting) CountSpatialIntersections(
        BasicFeatureLayer source,
        BasicFeatureLayer target,
        int limit)
    {
        try
        {
            using var sourceTable = source.GetTable();
            using var targetTable = target.GetTable();
            var targetSpatialReference = target.GetSpatialReference();
            var sampled = 0;
            var intersecting = 0;
            using var cursor = sourceTable.Search(new QueryFilter { WhereClause = "1=1", SubFields = "*" }, true);
            while (sampled < limit && cursor.MoveNext())
            {
                using var row = cursor.Current;
                if (row is not Feature feature)
                    continue;
                var geometry = feature.GetShape();
                if (geometry is null || geometry.IsEmpty)
                    continue;
                sampled++;
                try
                {
                    if (targetSpatialReference is not null
                        && geometry.SpatialReference is not null
                        && !geometry.SpatialReference.Name.Equals(targetSpatialReference.Name, StringComparison.OrdinalIgnoreCase))
                        geometry = GeometryEngine.Instance.Project(geometry, targetSpatialReference);
                    var filter = new SpatialQueryFilter
                    {
                        FilterGeometry = geometry,
                        SpatialRelationship = SpatialRelationship.Intersects,
                        WhereClause = "1=1",
                    };
                    using var matches = targetTable.Search(filter, true);
                    if (matches.MoveNext()) intersecting++;
                }
                catch
                {
                    // Une entité non projetable n'annule pas l'analyse du couple.
                }
            }
            return (sampled, intersecting);
        }
        catch
        {
            return (0, 0);
        }
    }

    private static IReadOnlyList<NativeVectorCompositionItem> BuildComposition(
        IReadOnlyList<NativeLayerProfile> profiles,
        string primaryLayerId)
    {
        var ordered = profiles
            .OrderBy(profile => DrawingPriority(profile, primaryLayerId))
            .ThenBy(profile => profile.Name, StringComparer.CurrentCultureIgnoreCase)
            .ToArray();
        return ordered.Select((profile, index) =>
        {
            var opacity = profile.GeometryType == "polygon" && profile.Role != "limites" ? 72 : 100;
            var labels = !string.IsNullOrWhiteSpace(profile.LabelField)
                         && (profile.Role is "localités" or "limites"
                             || profile.LayerId.Equals(primaryLayerId, StringComparison.Ordinal));
            var reason = profile.GeometryType switch
            {
                "point" => "Points placés au-dessus des surfaces pour rester visibles.",
                "line" => "Réseau placé au-dessus des polygones.",
                "polygon" when profile.Role == "limites" => "Limites conservées au-dessus des surfaces thématiques.",
                _ => "Surface thématique ordonnée sous les informations ponctuelles et linéaires.",
            };
            return new NativeVectorCompositionItem(
                profile.LayerId,
                profile.Name,
                profile.GeometryType,
                profile.Role,
                index + 1,
                opacity,
                labels,
                profile.RecommendedRenderer,
                profile.RecommendedPalette,
                reason);
        }).ToArray();
    }

    private static IReadOnlyList<NativeVectorOperation> BuildOperationPlan(
        IReadOnlyList<NativeVectorRelation> relations,
        IReadOnlyList<NativeLayerProfile> profiles,
        string primaryLayerId,
        string objective)
    {
        var primary = profiles.First(profile => profile.LayerId.Equals(primaryLayerId, StringComparison.Ordinal));
        var operations = new List<NativeVectorOperation>
        {
            new(1, "Contrôle des données", string.Join(", ", profiles.Select(profile => profile.Name)),
                "Géométries, attributs, doublons et systèmes de coordonnées", "Rapport de qualité", true, 1.0,
                "Sécurise les analyses avant toute superposition."),
        };
        var order = 2;
        foreach (var relation in relations
                     .Where(relation => relation.IntersectingFeatures > 0 || relation.ExtentOverlapPercent <= 0)
                     .OrderByDescending(relation => relation.LeftLayerId == primaryLayerId || relation.RightLayerId == primaryLayerId)
                     .ThenByDescending(relation => relation.Confidence)
                     .Take(12))
        {
            operations.Add(new NativeVectorOperation(
                order++,
                relation.Relation,
                $"{relation.LeftLayerName} + {relation.RightLayerName}",
                relation.SuggestedOperation,
                relation.ExpectedResult,
                relation.Confidence >= 0.80,
                relation.Confidence,
                relation.Evidence));
        }
        if (objective is "environnement" or "occupation_sol" or "agriculture" or "biodiversite")
            operations.Add(new NativeVectorOperation(
                order++, "Analyse par distances", primary.Name,
                "Anneaux 0–100 m, 100–250 m, 250–500 m et 500–1 000 m",
                "Statistiques de proximité par classe", false, 0.76,
                "Distances proposées pour mesurer la concentration des pressions autour des objets."));
        operations.Add(new NativeVectorOperation(
            order, "Composition cartographique", string.Join(", ", profiles.Select(profile => profile.Name)),
            "Ordre de dessin, transparence, symbologie cohérente et étiquetage sélectif",
            "Carte multi-couches lisible et légende non redondante", true, 0.96,
            "La composition est réversible et ne modifie aucune entité source."));
        return operations;
    }

    private static IEnumerable<string> BuildWorkspaceWarnings(
        IReadOnlyList<NativeLayerProfile> profiles,
        IReadOnlyList<NativeVectorRelation> relations)
    {
        foreach (var group in profiles
                     .Where(profile => !string.IsNullOrWhiteSpace(profile.SpatialReference))
                     .GroupBy(profile => profile.SpatialReference, StringComparer.OrdinalIgnoreCase)
                     .Skip(1))
            yield return $"Système de coordonnées différent détecté : {group.Key}. Une reprojection temporaire est requise pour les sorties analytiques.";
        var invalid = profiles.Sum(profile => profile.InvalidGeometryCount + profile.EmptyGeometryCount);
        if (invalid > 0)
            yield return $"{invalid} géométrie(s) invalide(s) ou vide(s) détectée(s) dans les échantillons.";
        if (relations.Count > 0 && relations.All(relation => relation.IntersectingFeatures == 0))
            yield return "Aucun croisement d'entités n'a été confirmé dans l'échantillon ; vérifiez les emprises et les projections.";
    }

    private static string BuildSummary(
        string mapName,
        IReadOnlyList<NativeLayerProfile> profiles,
        IReadOnlyList<NativeVectorRelation> relations,
        IReadOnlyList<NativeVectorOperation> operations,
        IReadOnlyList<string> warnings,
        bool deep)
    {
        var confirmed = relations.Count(relation => relation.IntersectingFeatures > 0);
        return $"Carte : {mapName}\nMode : {(deep ? "approfondi" : "rapide")}\n" +
               $"Couches vectorielles analysées : {profiles.Count}\nRelations examinées : {relations.Count}\n" +
               $"Relations confirmées : {confirmed}\nOpérations proposées : {operations.Count}\nAvertissements : {warnings.Count}";
    }

    private static string BuildPlanText(
        string objective,
        string primaryLayerId,
        IReadOnlyList<NativeLayerProfile> profiles,
        IReadOnlyList<NativeVectorCompositionItem> composition,
        IReadOnlyList<NativeVectorOperation> operations,
        IReadOnlyList<string> warnings)
    {
        var primary = profiles.First(profile => profile.LayerId.Equals(primaryLayerId, StringComparison.Ordinal));
        var lines = new List<string>
        {
            "VECTOR ENGINE · PLAN EXPLICABLE",
            $"Objectif : {objective}",
            $"Couche principale : {primary.Name} ({primary.Role}, confiance {primary.RoleConfidence:P0})",
            $"Couches prises en compte : {profiles.Count}",
            string.Empty,
            "OPÉRATIONS RECOMMANDÉES",
        };
        lines.AddRange(operations.Select(operation =>
            $"{operation.Order}. {operation.Name} — {operation.Method}\n   Entrées : {operation.InputLayers}\n   Sortie : {operation.Output} · confiance {operation.Confidence:P0}"));
        lines.Add(string.Empty);
        lines.Add("ORDRE CARTOGRAPHIQUE");
        lines.AddRange(composition.Select(item =>
            $"{item.OrderIndex}. {item.LayerName} — {item.Role} · opacité {item.OpacityPercent}%{(item.EnableLabels ? " · étiquettes" : string.Empty)}"));
        if (warnings.Count > 0)
        {
            lines.Add(string.Empty);
            lines.Add("POINTS À VÉRIFIER");
            lines.AddRange(warnings.Select(warning => $"• {warning}"));
        }
        lines.Add(string.Empty);
        lines.Add("Les données sources restent intactes. La composition peut être annulée intégralement.");
        return string.Join(Environment.NewLine, lines);
    }

    private static (string Relation, string Operation, string Output) RelationRule(
        string leftGeometry,
        string rightGeometry,
        double overlap)
    {
        var pair = new HashSet<string>([leftGeometry, rightGeometry], StringComparer.OrdinalIgnoreCase);
        if (overlap <= 0)
            return ("Proximité entre couches disjointes", "Plus proche / distances géodésiques", "Distances minimales, moyennes et médianes");
        if (pair.SetEquals(["point", "polygon"]))
            return ("Points contenus ou intersectant des polygones", "Jointure spatiale et agrégation", "Effectifs, densités et statistiques par zone");
        if (pair.SetEquals(["line", "polygon"]))
            return ("Lignes traversant des polygones", "Intersection par paire", "Longueur et densité du réseau par zone");
        if (leftGeometry == "polygon" && rightGeometry == "polygon")
            return ("Recouvrement de polygones", "Intersection par paire / découpage", "Surfaces et pourcentages de recouvrement");
        if (leftGeometry == "point" && rightGeometry == "point")
            return ("Proximité et concentration de points", "Plus proche / agrégation spatiale", "Distances, voisinage et densité");
        if (leftGeometry == "line" && rightGeometry == "line")
            return ("Croisement de réseaux", "Intersection et contrôle topologique", "Nœuds de croisement et tronçons communs");
        return ("Relation point–ligne", "Plus proche et intersection", "Distances au réseau et points de contact");
    }

    private static int DrawingPriority(NativeLayerProfile profile, string primaryLayerId)
    {
        var basePriority = profile.GeometryType switch
        {
            "point" => 10,
            "line" => 30,
            "polygon" when profile.Role == "limites" => 45,
            "polygon" => 60,
            _ => 70,
        };
        if (profile.Role == "localités") basePriority -= 3;
        if (profile.Role == "hydrographie" && profile.GeometryType == "line") basePriority += 2;
        if (profile.LayerId.Equals(primaryLayerId, StringComparison.Ordinal)) basePriority -= 1;
        return basePriority;
    }

    private static Envelope? SafeExtent(BasicFeatureLayer layer)
    {
        try
        {
            var extent = layer.QueryExtent();
            return extent is null || extent.IsEmpty ? null : extent;
        }
        catch
        {
            return null;
        }
    }

    private static double ExtentOverlapPercent(Envelope? left, Envelope? right)
    {
        if (left is null || right is null) return 0;
        var width = Math.Max(0, Math.Min(left.XMax, right.XMax) - Math.Max(left.XMin, right.XMin));
        var height = Math.Max(0, Math.Min(left.YMax, right.YMax) - Math.Max(left.YMin, right.YMin));
        var intersection = width * height;
        var leftArea = Math.Max(0, left.XMax - left.XMin) * Math.Max(0, left.YMax - left.YMin);
        var rightArea = Math.Max(0, right.XMax - right.XMin) * Math.Max(0, right.YMax - right.YMin);
        var denominator = Math.Min(leftArea, rightArea);
        return denominator <= 0 ? 0 : Math.Clamp(intersection / denominator * 100.0, 0, 100);
    }

    private static string GeometryType(BasicFeatureLayer layer)
    {
        try
        {
            using var table = layer.GetTable();
            using var definition = table.GetDefinition();
            if (definition is not FeatureClassDefinition featureDefinition) return "unknown";
            var value = featureDefinition.GetShapeType().ToString().ToLowerInvariant();
            if (value.Contains("point")) return "point";
            if (value.Contains("line")) return "line";
            if (value.Contains("polygon")) return "polygon";
        }
        catch
        {
            // Les couches de service indisponibles restent visibles dans l'inventaire.
        }
        return "unknown";
    }
}
