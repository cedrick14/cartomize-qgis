using System.Text.Json;
using System.Text.RegularExpressions;
using ArcGIS.Desktop.Core;
using ArcGIS.Desktop.Framework.Threading.Tasks;
using ArcGIS.Desktop.Mapping;

namespace Cartomize.ArcGISPro.Services;

internal sealed record NativeBatchResult(int Total, int Completed, IReadOnlyList<string> Outputs, IReadOnlyList<string> Errors);

/// <summary>Production en série native fondée sur les mêmes recettes 10.5.1.</summary>
internal static partial class NativeBatchService
{
    public static async Task<NativeBatchResult> RunAsync(
        string manifestPath,
        Map map,
        string templatePath,
        bool visibleOnly,
        double marginPercent,
        int contextOpacityPercent)
    {
        using var document = JsonDocument.Parse(File.ReadAllText(manifestPath));
        var root = document.RootElement;
        if (!root.TryGetProperty("jobs", out var jobsElement) || jobsElement.ValueKind != JsonValueKind.Array)
            throw new InvalidOperationException("Le manifeste Cartomize ne contient aucune série jobs valide.");
        var baseDirectory = Path.GetDirectoryName(Path.GetFullPath(manifestPath)) ?? Module.UserDataDirectory;
        var outputDirectory = CartomizeDataService.Text(root, "output_directory", Path.Combine(baseDirectory, "exports"));
        if (!Path.IsPathRooted(outputDirectory)) outputDirectory = Path.Combine(baseDirectory, outputDirectory);
        Directory.CreateDirectory(outputDirectory);
        var dpi = Math.Clamp((int)CartomizeDataService.Number(root, "dpi", 600), 96, 1200);
        var keepLayouts = CartomizeDataService.Boolean(root, "keep_layouts");
        var jobs = jobsElement.EnumerateArray().Take(5000).Select(value => value.Clone()).ToArray();
        var outputs = new List<string>();
        var errors = new List<string>();
        var completed = 0;
        foreach (var job in jobs)
        {
            var jobId = SafeName(CartomizeDataService.Text(job, "job_id", $"carte-{completed + 1:0000}"));
            try
            {
                var result = await NativeLayoutService.CreateAsync(new NativeLayoutRequest(
                    map,
                    templatePath,
                    $"Cartomize — {jobId}",
                    CartomizeDataService.Text(job, "title", "TITRE DE LA CARTE"),
                    CartomizeDataService.Text(job, "subtitle"),
                    CartomizeDataService.Text(job, "sources"),
                    visibleOnly,
                    marginPercent,
                    true,
                    null,
                    contextOpacityPercent));
                var outputName = SafeName(CartomizeDataService.Text(job, "output_name", jobId));
                var formats = job.TryGetProperty("output_formats", out var formatsElement) && formatsElement.ValueKind == JsonValueKind.Array
                    ? formatsElement.EnumerateArray().Select(value => (value.GetString() ?? string.Empty).ToLowerInvariant()).ToArray()
                    : ["pdf", "png"];
                foreach (var format in formats.Where(value => value is "pdf" or "png" or "svg").Distinct(StringComparer.OrdinalIgnoreCase))
                {
                    var output = Path.Combine(outputDirectory, $"{outputName}.{format}");
                    await NativeLayoutService.ExportAsync(result.Layout, output, dpi);
                    outputs.Add(output);
                }
                completed++;
                if (!keepLayouts)
                {
                    await QueuedTask.Run(() =>
                    {
                        var item = Project.Current?.GetItems<LayoutProjectItem>()
                            .FirstOrDefault(value => value.Name.Equals(result.LayoutName, StringComparison.OrdinalIgnoreCase));
                        if (item is not null) Project.Current.RemoveItem(item);
                    });
                }
            }
            catch (Exception exception)
            {
                errors.Add($"{jobId} : {exception.Message}");
            }
        }
        return new NativeBatchResult(jobs.Length, completed, outputs, errors);
    }

    private static string SafeName(string value)
    {
        var cleaned = UnsafeFileNameCharacters().Replace(value.Trim(), "-").Trim('-', '.', ' ');
        return string.IsNullOrWhiteSpace(cleaned) ? "carte" : cleaned[..Math.Min(cleaned.Length, 120)];
    }

    [GeneratedRegex("[\\\\/:*?\"<>|]+", RegexOptions.CultureInvariant)]
    private static partial Regex UnsafeFileNameCharacters();
}
