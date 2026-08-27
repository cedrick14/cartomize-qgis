using ArcGIS.Desktop.Framework.Contracts;
using ArcGIS.Desktop.Framework.Dialogs;
using Cartomize.ArcGISPro.Services;
using Cartomize.ArcGISPro.Views;

namespace Cartomize.ArcGISPro.Commands;

internal sealed class OpenDockPaneButton : Button
{
    protected override void OnClick()
    {
        try
        {
            CartomizeDockPaneViewModel.Show();
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write("Ouverture du panneau Cartomize", exception);
            MessageBox.Show(
                $"Cartomize n’a pas pu s’ouvrir. ArcGIS Pro peut continuer à fonctionner.\n\n" +
                $"Journal : {DiagnosticLog.FilePath}\n\n" +
                $"Erreur : {exception.Message}",
                "Cartomize 10.5.1");
        }
    }
}

internal abstract class ToolButton : Button
{
    protected abstract string ToolName { get; }
    protected override void OnClick()
    {
        try
        {
            GeoprocessingService.Open(ToolName);
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write($"Ouverture de l’outil {ToolName}", exception);
            MessageBox.Show(
                $"L’outil Cartomize n’a pas pu s’ouvrir.\n\nJournal : {DiagnosticLog.FilePath}\n\nErreur : {exception.Message}",
                "Cartomize 10.5.1");
        }
    }
}

internal sealed class AuditButton : ToolButton { protected override string ToolName => "AuditProject"; }
internal sealed class AutopilotButton : ToolButton { protected override string ToolName => "AutopilotMap"; }
internal sealed class VectorButton : ToolButton { protected override string ToolName => "VectorIntelligence"; }
internal sealed class RasterButton : ToolButton { protected override string ToolName => "RasterIntelligence"; }
internal sealed class GeoButton : ToolButton { protected override string ToolName => "GeoIntelligence"; }
internal sealed class LayoutButton : ToolButton { protected override string ToolName => "CreateLayout"; }
internal sealed class BatchButton : ToolButton { protected override string ToolName => "BatchMaps"; }
internal sealed class ReplayButton : ToolButton { protected override string ToolName => "ReplayRecipe"; }
