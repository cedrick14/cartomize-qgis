using System.Windows;
using System.Windows.Controls;
using Cartomize.ArcGISPro.Services;

namespace Cartomize.ArcGISPro.Views;

public partial class CartomizeDockPaneView : UserControl
{
    private bool _contentLoaded;

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
        StartupGuard.Stage("Conteneur Cartomize affiché");

        try
        {
            // Laisser ArcGIS Pro achever l'ancrage de son DockPane avant de
            // construire l'arbre visuel complet des sept onglets Cartomize.
            await System.Windows.Threading.Dispatcher.Yield(
                System.Windows.Threading.DispatcherPriority.ContextIdle);

            if (!_contentLoaded)
            {
                StartupGuard.Stage("Construction différée de l’interface Cartomize");
                ContentHost.Content = new CartomizeContentView();
                _contentLoaded = true;
                StartupGuard.Stage("Interface Cartomize attachée au conteneur");

                // Exécuter la première mesure dans ce bloc protégé permet de
                // journaliser les erreurs WPF gérées et d'afficher le panneau
                // de secours sans arrêter ArcGIS Pro.
                ContentHost.UpdateLayout();
                StartupGuard.Stage("Interface Cartomize mesurée");
            }

            if (DataContext is CartomizeDockPaneViewModel viewModel)
                await viewModel.InitializeAfterViewLoadedAsync();
            else
                DiagnosticLog.Write("Le modèle de vue Cartomize n’est pas associé à la vue.");
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write("Initialisation différée du panneau Cartomize", exception);
            ContentHost.Content = new Border
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
