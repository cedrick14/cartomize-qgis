using System.Windows;
using System.Windows.Controls;
using Cartomize.ArcGISPro.Services;

namespace Cartomize.ArcGISPro.Views;

public partial class CartomizeDockPaneView : UserControl
{
    public CartomizeDockPaneView()
    {
        StartupGuard.EnsureInitialized("Construction de la vue Cartomize");
        try
        {
            StartupGuard.Stage("Chargement XAML commencé");
            InitializeComponent();
            StartupGuard.Stage("Chargement XAML terminé");
            Loaded += (_, _) => StartupGuard.Stage("Vue Cartomize affichée");
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write("Chargement XAML du panneau Cartomize", exception);
            Content = new Border
            {
                Padding = new Thickness(16),
                Child = new TextBlock
                {
                    Text = $"Impossible de charger l’interface Cartomize.\n\nJournal : {DiagnosticLog.FilePath}\n\nErreur : {exception.Message}",
                    TextWrapping = TextWrapping.Wrap,
                },
            };
        }
    }
}
