using ArcGIS.Desktop.Core;
using ArcGIS.Desktop.Framework.Threading.Tasks;
using ArcGIS.Desktop.Layouts;
using ArcGIS.Desktop.Mapping;

namespace Cartomize.ArcGISPro.Services;

internal sealed record NativeAuditFinding(
    string Severity,
    string Code,
    string LayerId,
    string LayerName,
    string Message,
    string Remediation);

internal sealed record NativeAuditResult(int Score, string Status, IReadOnlyList<NativeAuditFinding> Findings);

/// <summary>Contrôle qualité ArcGIS natif correspondant à quality.py.</summary>
internal static class NativeAuditService
{
    private static readonly Dictionary<string, int> Weights = new(StringComparer.OrdinalIgnoreCase)
    {
        ["critical"] = 25,
        ["high"] = 12,
        ["medium"] = 6,
        ["low"] = 2,
        ["info"] = 0,
    };

    public static Task<NativeAuditResult> RunAsync(Map? map)
        => QueuedTask.Run(() =>
        {
            var findings = new List<NativeAuditFinding>();
            var layers = map?.GetLayersAsFlattenedList()
                .Where(layer => layer is BasicFeatureLayer or RasterLayer)
                .Take(500)
                .ToArray() ?? [];
            if (layers.Length == 0)
                findings.Add(new NativeAuditFinding("critical", "PROJECT_NO_LAYER", "", "", "Le projet ne contient aucune couche.", "Charger au moins une couche vectorielle ou raster valide."));
            if (map?.SpatialReference is null || map.SpatialReference.IsUnknown)
                findings.Add(new NativeAuditFinding("critical", "PROJECT_CRS_MISSING", "", "", "Le système de coordonnées de la carte n’est pas défini.", "Définir un système de coordonnées adapté au territoire."));

            foreach (var layer in layers)
            {
                var spatialReference = layer.GetSpatialReference();
                if (spatialReference is null || spatialReference.IsUnknown)
                    findings.Add(new NativeAuditFinding("high", "LAYER_CRS_MISSING", layer.URI, layer.Name, "La couche ne possède pas de système de coordonnées valide.", "Définir le système de coordonnées source réel."));
                try
                {
                    var extent = layer.QueryExtent();
                    if (extent is null || extent.IsEmpty)
                        findings.Add(new NativeAuditFinding("high", "LAYER_EMPTY_EXTENT", layer.URI, layer.Name, "L’emprise de la couche est vide.", "Vérifier les données et les filtres actifs."));
                }
                catch (Exception exception)
                {
                    findings.Add(new NativeAuditFinding("high", "LAYER_SOURCE_ERROR", layer.URI, layer.Name, "La source de la couche est inaccessible.", exception.Message));
                }

                if (layer is BasicFeatureLayer featureLayer)
                {
                    try
                    {
                        using var table = featureLayer.GetTable();
                        if (table is null || table.GetCount() == 0)
                            findings.Add(new NativeAuditFinding("medium", "VECTOR_EMPTY", layer.URI, layer.Name, "La couche vectorielle ne contient aucune entité.", "Retirer la couche ou corriger sa source."));
                    }
                    catch (Exception exception)
                    {
                        findings.Add(new NativeAuditFinding("critical", "LAYER_INVALID", layer.URI, layer.Name, "La couche est invalide.", exception.Message));
                    }
                }
                else if (layer is RasterLayer rasterLayer)
                {
                    try
                    {
                        using var raster = rasterLayer.GetRaster();
                        if (raster is null || NativeLayerService.GetRasterBandCount(raster, rasterLayer) < 1)
                            findings.Add(new NativeAuditFinding("high", "RASTER_NO_BAND", layer.URI, layer.Name, "Le raster ne contient aucune bande lisible.", "Vérifier le fichier raster et sa source."));
                    }
                    catch (Exception exception)
                    {
                        findings.Add(new NativeAuditFinding("critical", "LAYER_INVALID", layer.URI, layer.Name, "Le raster est invalide.", exception.Message));
                    }
                }
            }

            if (Project.Current?.GetItems<LayoutProjectItem>().Any() != true)
                findings.Add(new NativeAuditFinding("medium", "LAYOUT_NONE", "", "", "Le projet ne contient aucune mise en page.", "Créer une mise en page Cartomize."));

            var score = Math.Clamp(100 - findings.Sum(item => Weights.GetValueOrDefault(item.Severity)), 0, 100);
            var status = score >= 85 ? "Conforme" : score >= 65 ? "À améliorer" : "Non conforme";
            return new NativeAuditResult(score, status, findings);
        });
}
