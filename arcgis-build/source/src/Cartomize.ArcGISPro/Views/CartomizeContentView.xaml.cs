using System.Windows.Controls;
using Cartomize.ArcGISPro.Services;

namespace Cartomize.ArcGISPro.Views;

/// <summary>
/// Interface Cartomize 10.5.1 complète, chargée seulement après que le
/// DockPane hôte a été attaché à l'arbre visuel d'ArcGIS Pro.
/// </summary>
public partial class CartomizeContentView : UserControl
{
    public CartomizeContentView()
    {
        StartupGuard.Stage("Construction du contenu visuel Cartomize");
        try
        {
            StartupGuard.Stage("Chargement XAML du contenu commencé");
            InitializeComponent();
            StartupGuard.Stage("Chargement XAML du contenu terminé");
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write("Chargement XAML du contenu Cartomize", exception);
            throw;
        }
    }
}
