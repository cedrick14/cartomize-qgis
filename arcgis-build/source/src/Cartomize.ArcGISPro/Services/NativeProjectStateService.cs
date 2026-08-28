using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using ArcGIS.Desktop.Core;
using ArcGIS.Desktop.Framework.Threading.Tasks;
using ArcGIS.Desktop.Mapping;

namespace Cartomize.ArcGISPro.Services;

internal sealed record NativeMapOpsResult(bool Changed, string CurrentHash, string PreviousHash, string Message);

/// <summary>Instantané MapOps reproductible construit avec le modèle ArcGIS Pro.</summary>
internal static class NativeProjectStateService
{
    public static async Task<string> CaptureJsonAsync()
    {
        var state = await QueuedTask.Run(() =>
        {
            var maps = Project.Current?.GetItems<MapProjectItem>()
                .OrderBy(item => item.Name, StringComparer.OrdinalIgnoreCase)
                .Select(item =>
                {
                    var map = item.GetMap();
                    var layers = map.GetLayersAsFlattenedList()
                        .Where(layer => layer is BasicFeatureLayer or RasterLayer)
                        .Select(layer => new
                        {
                            id = layer.URI,
                            name = layer.Name,
                            type = layer is RasterLayer ? "raster" : "vector",
                            visible = layer.IsVisible,
                            transparency = layer.GetTransparency(),
                            crs = layer.GetSpatialReference()?.Name ?? string.Empty,
                        })
                        .OrderBy(layer => layer.id, StringComparer.Ordinal)
                        .ToArray();
                    return new
                    {
                        name = map.Name,
                        crs = map.SpatialReference?.Name ?? string.Empty,
                        layers,
                    };
                })
                .ToArray() ?? [];
            var layouts = Project.Current?.GetItems<LayoutProjectItem>()
                .Select(item => item.Name)
                .OrderBy(name => name, StringComparer.OrdinalIgnoreCase)
                .ToArray() ?? [];
            return new { schema_version = 1, cartomize_version = "10.5.1", maps, layouts };
        });
        return JsonSerializer.Serialize(state, new JsonSerializerOptions { WriteIndented = true });
    }

    public static async Task<NativeMapOpsResult> CompareAsync(string baselinePath, string currentPath)
    {
        var current = await CaptureJsonAsync();
        Directory.CreateDirectory(Path.GetDirectoryName(currentPath) ?? Module.UserDataDirectory);
        File.WriteAllText(currentPath, current);
        var currentHash = Hash(current);
        if (!File.Exists(baselinePath))
            return new NativeMapOpsResult(true, currentHash, string.Empty, "Référence MapOps absente.");
        var previous = File.ReadAllText(baselinePath);
        var previousHash = Hash(previous);
        var changed = !currentHash.Equals(previousHash, StringComparison.OrdinalIgnoreCase);
        return new NativeMapOpsResult(
            changed,
            currentHash,
            previousHash,
            changed ? "Le projet a changé depuis la référence." : "Aucun changement détecté.");
    }

    public static async Task WriteBaselineAsync(string path)
    {
        var json = await CaptureJsonAsync();
        Directory.CreateDirectory(Path.GetDirectoryName(path) ?? Module.UserDataDirectory);
        File.WriteAllText(path, json);
    }

    private static string Hash(string value)
        => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value))).ToLowerInvariant();
}
