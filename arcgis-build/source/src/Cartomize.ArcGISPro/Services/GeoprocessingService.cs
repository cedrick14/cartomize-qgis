using System.IO;
using ArcGIS.Desktop.Core.Geoprocessing;
using ArcGIS.Desktop.Framework.Dialogs;

namespace Cartomize.ArcGISPro.Services;

internal static class GeoprocessingService
{
    internal sealed record ExecutionResult(
        bool Succeeded,
        string ReturnValue,
        string Messages,
        int ErrorCode);

    public static void Open(string toolName, params object[] values)
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
        Geoprocessing.OpenToolDialog(toolPath, Geoprocessing.MakeValueArray(values));
    }

    public static async Task<ExecutionResult> ExecuteAsync(string toolName, params object?[] values)
    {
        var toolbox = Module.ToolboxPath;
        if (!File.Exists(toolbox))
            return new ExecutionResult(false, string.Empty, $"Boîte à outils introuvable : {toolbox}", -1);

        var toolPath = $"{toolbox}\\{toolName}";
        var result = await Geoprocessing.ExecuteToolAsync(
            toolPath,
            Geoprocessing.MakeValueArray(values),
            null,
            null,
            GPExecuteToolFlags.RefreshProjectItems | GPExecuteToolFlags.AddToHistory);
        var messages = string.Join(
            Environment.NewLine,
            result.Messages.Select(message => message.Text));
        return new ExecutionResult(
            !result.IsFailed,
            result.ReturnValue ?? string.Empty,
            messages,
            result.ErrorCode);
    }
}
