using System.Security.Cryptography;
using System.Text;
using ArcGIS.Core.CIM;
using ArcGIS.Desktop.Framework.Threading.Tasks;
using ArcGIS.Desktop.Layouts;
using ArcGIS.Desktop.Mapping;

namespace Cartomize.ArcGISPro.Services;

/// <summary>
/// Maintient un seul contour vectoriel noir par raster dans une couche de
/// graphiques de la carte. Le contour est un rectangle creux fondé sur
/// l'emprise native du raster et reste donc visible dans les mises en page.
/// </summary>
internal static class NativeRasterOutlineService
{
    private const string GraphicsLayerName = "Cartomize · Contours raster";

    public static Task<bool> ExistsAsync(RasterLayer layer)
        => QueuedTask.Run(() =>
        {
            var map = ResolveMap(layer);
            var graphics = map?.GetLayersAsFlattenedList()
                .OfType<GraphicsLayer>()
                .FirstOrDefault(item => item.Name.Equals(GraphicsLayerName, StringComparison.Ordinal));
            return graphics?.FindElement(ElementName(layer)) is not null;
        });

    public static Task<bool> ApplyAsync(RasterLayer layer, bool enabled, double widthPoints)
        => QueuedTask.Run(() =>
        {
            var map = ResolveMap(layer);
            if (map is null || map.MapType != MapType.Map) return false;
            var graphics = map.GetLayersAsFlattenedList()
                .OfType<GraphicsLayer>()
                .FirstOrDefault(item => item.Name.Equals(GraphicsLayerName, StringComparison.Ordinal));
            var elementName = ElementName(layer);
            var existing = graphics?.FindElement(elementName);
            if (existing is not null)
                graphics!.RemoveElement(existing);
            if (!enabled) return true;

            graphics ??= LayerFactory.Instance.CreateLayer<GraphicsLayer>(
                new GraphicsLayerCreationParams
                {
                    Name = GraphicsLayerName,
                    IsVisible = true,
                    MapMemberIndex = 0,
                },
                map);
            var extent = layer.QueryExtent();
            if (extent is null || extent.IsEmpty) return false;
            var stroke = SymbolFactory.Instance.ConstructStroke(
                ColorFactory.Instance.BlackRGB,
                Math.Clamp(widthPoints, 0.4, 4.0),
                SimpleLineStyle.Solid);
            var symbol = SymbolFactory.Instance.ConstructPolygonSymbol(
                CIMColor.CreateRGBColor(255, 255, 255, 0),
                SimpleFillStyle.Solid,
                stroke);
            ElementFactory.Instance.CreateGraphicElement(graphics, extent, symbol, elementName);
            return true;
        });

    private static Map? ResolveMap(RasterLayer layer)
    {
        var map = MapView.Active?.Map;
        if (map is null) return null;
        var uri = layer.URI ?? string.Empty;
        return map.GetLayersAsFlattenedList().Any(item =>
            ReferenceEquals(item, layer)
            || !string.IsNullOrWhiteSpace(uri) && string.Equals(item.URI, uri, StringComparison.Ordinal))
            ? map
            : null;
    }

    private static string ElementName(RasterLayer layer)
    {
        var identity = layer.URI ?? layer.Name;
        var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(identity)))[..12];
        return $"Contour raster · {layer.Name} · {hash}";
    }
}
