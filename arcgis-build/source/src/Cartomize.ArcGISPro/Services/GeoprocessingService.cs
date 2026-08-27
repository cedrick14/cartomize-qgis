using System.IO;
using ArcGIS.Desktop.Core.Geoprocessing;
using ArcGIS.Desktop.Framework.Dialogs;

namespace Cartomize.ArcGISPro.Services;

internal static class GeoprocessingService
{
    public static void Open(string toolName)
    {
        var toolbox = Module.ToolboxPath;
        if (!File.Exists(toolbox))
        {
            MessageBox.Show(
                $"La boîte à outils Cartomize est introuvable :\n{toolbox}",
                "Cartomize");
            return;
        }

        var toolPath = $"{toolbox}\\{toolName}";
        Geoprocessing.OpenToolDialog(toolPath, Geoprocessing.MakeValueArray());
    }
}
