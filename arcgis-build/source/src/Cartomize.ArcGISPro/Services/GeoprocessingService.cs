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

    public static void Open(string toolName, params object?[] values)
    {
        var toolbox = Module.ToolboxPath;
        if (!File.Exists(toolbox))
        {
            MessageBox.Show(
                $"La boîte à outils Cartomize est introuvable :\n{toolbox}",
                "Cartomize");
            return;
        }

        try
        {
            var toolPath = Path.Combine(toolbox, toolName);
            Geoprocessing.OpenToolDialog(toolPath, Geoprocessing.MakeValueArray(values));
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write($"Ouverture du géotraitement : {toolName}", exception);
            MessageBox.Show(exception.Message, "Cartomize");
        }
    }

    public static async Task<ExecutionResult> ExecuteAsync(string toolName, params object?[] values)
    {
        var toolbox = Module.ToolboxPath;
        if (!File.Exists(toolbox))
            return new ExecutionResult(false, string.Empty, $"Boîte à outils introuvable : {toolbox}", -1);

        var toolPath = Path.Combine(toolbox, toolName);
        DiagnosticLog.Write($"Géotraitement démarré : {toolName} ({values.Length} paramètre(s))");
        try
        {
            var result = await Geoprocessing.ExecuteToolAsync(
                toolPath,
                Geoprocessing.MakeValueArray(values),
                null,
                null,
                GPExecuteToolFlags.RefreshProjectItems |
                GPExecuteToolFlags.AddToHistory |
                GPExecuteToolFlags.GPThread);

            if (result is null)
            {
                const string message = "ArcGIS Pro n’a retourné aucun résultat de géotraitement.";
                DiagnosticLog.Write($"Géotraitement sans résultat : {toolName}");
                return new ExecutionResult(false, string.Empty, message, -1);
            }

            var messages = FormatMessages(result.Messages);
            if (string.IsNullOrWhiteSpace(messages) && (result.IsFailed || result.IsCanceled))
                messages = FormatMessages(result.ErrorMessages);
            if (string.IsNullOrWhiteSpace(messages) && result.IsCanceled)
                messages = "Opération annulée.";
            if (string.IsNullOrWhiteSpace(messages) && result.IsFailed)
                messages = $"Le géotraitement a échoué (code {result.ErrorCode}).";

            DiagnosticLog.Write(
                $"Géotraitement terminé : {toolName} — code {result.ErrorCode} — " +
                $"échec={result.IsFailed} — annulé={result.IsCanceled}");
            return new ExecutionResult(
                !result.IsFailed && !result.IsCanceled,
                result.ReturnValue ?? string.Empty,
                messages,
                result.ErrorCode);
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write($"Géotraitement .NET : {toolName}", exception);
            return new ExecutionResult(false, string.Empty, exception.Message, -1);
        }
    }

    private static string FormatMessages(IEnumerable<IGPMessage>? messages)
        => messages is null
            ? string.Empty
            : string.Join(
                Environment.NewLine,
                messages
                    .Where(message => message is not null && !string.IsNullOrWhiteSpace(message.Text))
                    .Select(message => message.Text));
}
