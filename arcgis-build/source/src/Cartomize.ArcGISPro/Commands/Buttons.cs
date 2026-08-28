using ArcGIS.Desktop.Framework.Contracts;
using ArcGIS.Desktop.Framework.Dialogs;
using Cartomize.ArcGISPro.Services;
using Cartomize.ArcGISPro.Views;

namespace Cartomize.ArcGISPro.Commands;

internal sealed class OpenDockPaneButton : Button
{
    protected override void OnClick()
    {
        StartupGuard.EnsureInitialized("Clic sur Ouvrir Cartomize");
        try
        {
            StartupGuard.Stage("Recherche du dockpane");
            CartomizeDockPaneViewModel.Show();
            StartupGuard.Stage("Activation du dockpane terminée");
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
