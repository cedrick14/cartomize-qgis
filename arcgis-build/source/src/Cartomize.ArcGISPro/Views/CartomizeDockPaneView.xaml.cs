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
            Loaded += OnLoaded;
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

    private async void OnLoaded(object sender, RoutedEventArgs args)
    {
        Loaded -= OnLoaded;
        StartupGuard.Stage("Vue Cartomize affichée");

        try
        {
            // Laisser ArcGIS Pro achever la mesure, le rendu et l'ancrage du
            // DockPane avant de remplir les collections liées à l'interface.
            await System.Windows.Threading.Dispatcher.Yield(
                System.Windows.Threading.DispatcherPriority.ContextIdle);

            if (DataContext is CartomizeDockPaneViewModel viewModel)
                await viewModel.InitializeAfterViewLoadedAsync();
            else
                DiagnosticLog.Write("Le modèle de vue Cartomize n’est pas associé à la vue.");
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write("Initialisation différée du panneau Cartomize", exception);
        }
    }
}
