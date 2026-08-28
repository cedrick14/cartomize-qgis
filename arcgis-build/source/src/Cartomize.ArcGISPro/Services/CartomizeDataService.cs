using System.Collections.ObjectModel;
using System.IO;
using System.Text.Json;
using Cartomize.ArcGISPro.Views;

namespace Cartomize.ArcGISPro.Services;

internal static class CartomizeDataService
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        WriteIndented = true,
    };

    public static IReadOnlyList<TemplateItem> LoadTemplates()
    {
        var root = Module.TemplatesDirectory;
        var catalogPath = Path.Combine(root, "offline_catalog.json");
        using var catalog = JsonDocument.Parse(File.ReadAllText(catalogPath));
        var templates = new List<TemplateItem>();
        foreach (var entry in catalog.RootElement.GetProperty("templates").EnumerateArray())
        {
            var relative = entry.GetProperty("path").GetString() ?? string.Empty;
            var fullPath = Path.GetFullPath(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
            if (!fullPath.StartsWith(Path.GetFullPath(root), StringComparison.OrdinalIgnoreCase))
                continue;
            using var document = JsonDocument.Parse(File.ReadAllText(fullPath));
            var item = document.RootElement;
            var layout = item.TryGetProperty("layout_json", out var layoutElement) ? layoutElement : default;
            var elementTypes = layout.ValueKind == JsonValueKind.Object
                && layout.TryGetProperty("elements", out var elements)
                && elements.ValueKind == JsonValueKind.Array
                    ? elements.EnumerateArray()
                        .Select(value => Text(value, "type"))
                        .ToArray()
                    : [];
            var id = Path.ChangeExtension(relative.Replace('\\', '/'), null) ?? relative;
            templates.Add(new TemplateItem(
                id,
                Text(item, "name", id),
                Text(item, "category", id.Split('/')[0]),
                Text(item, "description", string.Empty),
                Text(item, "page_format", layout.ValueKind == JsonValueKind.Object ? Text(layout, "page_format", string.Empty) : string.Empty),
                fullPath)
            {
                MapFrameCount = elementTypes.Count(value => value == "map_frame"),
                LegendCount = elementTypes.Count(value => value == "legend"),
                ChartCount = elementTypes.Count(value => value == "chart"),
                TableCount = elementTypes.Count(value => value == "table"),
            });
        }
        return templates
            .OrderBy(item => item.Category, StringComparer.CurrentCultureIgnoreCase)
            .ThenBy(item => item.Name, StringComparer.CurrentCultureIgnoreCase)
            .ToArray();
    }

    public static JsonDocument? ReadJson(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
            return null;
        return JsonDocument.Parse(File.ReadAllText(path));
    }

    public static void WriteJson(string path, object value)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path) ?? Module.UserDataDirectory);
        var temporary = path + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(value, JsonOptions));
        File.Move(temporary, path, true);
    }

    public static string ReportPath(string name) => Path.Combine(Module.UserDataDirectory, name);

    public static string Text(JsonElement element, string property, string fallback = "")
    {
        if (!element.TryGetProperty(property, out var value))
            return fallback;
        return value.ValueKind == JsonValueKind.String ? value.GetString() ?? fallback : value.ToString();
    }

    public static double Number(JsonElement element, string property, double fallback = 0)
    {
        if (!element.TryGetProperty(property, out var value))
            return fallback;
        return value.TryGetDouble(out var result) ? result : fallback;
    }

    public static bool Boolean(JsonElement element, string property, bool fallback = false)
    {
        if (!element.TryGetProperty(property, out var value))
            return fallback;
        return value.ValueKind is JsonValueKind.True or JsonValueKind.False ? value.GetBoolean() : fallback;
    }
}
