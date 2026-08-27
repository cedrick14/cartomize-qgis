using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Linq;
using System.Windows;
using System.Windows.Input;
using ArcGIS.Desktop.Framework;
using ArcGIS.Desktop.Framework.Contracts;
using ArcGIS.Desktop.Framework.Threading.Tasks;
using ArcGIS.Desktop.Mapping;
using Cartomize.ArcGISPro.Services;

namespace Cartomize.ArcGISPro.Views;

internal sealed class CartomizeDockPaneViewModel : DockPane
{
    private const string DockPaneId = "Cartomize_ArcGISPro_DockPane";
    private readonly HashSet<string> _rasterLayerNames = new(StringComparer.OrdinalIgnoreCase);
    private string? _selectedLayerName;
    private string _projectSummary = "0 couche(s)\n0 visible(s)\n0 invalide(s)";
    private string _recommendationText = "Sélectionnez une couche vectorielle ou raster valide.";
    private bool _isRasterLayer;

    protected CartomizeDockPaneViewModel()
    {
        AuditCommand = Tool("AuditProject");
        AutopilotCommand = Tool("AutopilotMap");
        AnalyzeAutomationCommand = Tool("GeoIntelligence");
        GenerateAllCommand = Tool("AutopilotMap");
        SaveRecipeCommand = Tool("AutopilotMap");
        ReplayCommand = Tool("ReplayRecipe");
        VectorCommand = Tool("VectorIntelligence");
        RasterCommand = Tool("RasterIntelligence");
        GeoCommand = Tool("GeoIntelligence");
        LayoutCommand = Tool("CreateLayout");
        BatchCommand = Tool("BatchMaps");
        MapOpsCommand = Tool("MapOpsCheck");
        LabelAuditCommand = Tool("AuditProject");
        DiagnosticsCommand = new DelegateCommand(() => _ = RefreshProjectAsync());

        AnalyzeLayerCommand = new DelegateCommand(AnalyzeSelectedLayer);
        ApplyRecommendationCommand = new DelegateCommand(ApplyRecommendation);
        UndoStyleCommand = NativeCommand("esri_core_undoButton");
        ImportDataCommand = NativeCommand("esri_mapping_addDataButton");
        ZoomLayerCommand = NativeCommand("esri_mapping_zoomToLayer");
        LayerPropertiesCommand = NativeCommand("esri_mapping_layerProperties");
        SynchronizeLayoutCommand = Tool("CreateLayout");
        OpenLayoutCommand = NativeCommand("esri_layouts_openLayout");
        RefreshPreviewCommand = NativeCommand("esri_mapping_refreshView");
        OptimizeLayoutCommand = Tool("CreateLayout");
        ExportLayoutCommand = NativeCommand("esri_layouts_exportLayout");
        CopyReportCommand = new DelegateCommand(() => Clipboard.SetText(ProjectSummary));
        SelectManifestCommand = Tool("BatchMaps");
        CreateManifestCommand = Tool("BatchMaps");
        ApproveLayoutCommand = Tool("AuditProject");
        ExportCertificateCommand = Tool("AuditProject");
        CommunityCommand = new DelegateCommand(OpenCommunityPortal);
        RefreshCommunityCommand = new DelegateCommand(OpenCommunityPortal);

        _ = RefreshProjectAsync();
    }

    public ObservableCollection<string> LayerNames { get; } = new();
    public string VersionText => "Cartomize 10.5.1";
    public string FooterStatus => ProjectSummary.Replace("\n", ", ");
    public string DiagnosticText =>
        "Cartomize 10.5.1\nArcGIS Pro 3.7\n.NET 10\n24 maquettes hors ligne";

    public string ProjectSummary
    {
        get => _projectSummary;
        private set
        {
            if (SetProperty(ref _projectSummary, value))
                NotifyPropertyChanged(nameof(FooterStatus));
        }
    }

    public string RecommendationText
    {
        get => _recommendationText;
        private set => SetProperty(ref _recommendationText, value);
    }

    public bool IsRasterLayer
    {
        get => _isRasterLayer;
        private set => SetProperty(ref _isRasterLayer, value);
    }

    public string? SelectedLayerName
    {
        get => _selectedLayerName;
        set
        {
            if (!SetProperty(ref _selectedLayerName, value))
                return;
            IsRasterLayer = !string.IsNullOrWhiteSpace(value) && _rasterLayerNames.Contains(value);
            RecommendationText = string.IsNullOrWhiteSpace(value)
                ? "Sélectionnez une couche vectorielle ou raster valide."
                : "Cliquez sur « Analyser la couche sélectionnée » pour obtenir une proposition. Aucune entité n’est parcourue automatiquement.";
        }
    }

    public ICommand AuditCommand { get; }
    public ICommand AutopilotCommand { get; }
    public ICommand AnalyzeAutomationCommand { get; }
    public ICommand GenerateAllCommand { get; }
    public ICommand SaveRecipeCommand { get; }
    public ICommand ReplayCommand { get; }
    public ICommand VectorCommand { get; }
    public ICommand RasterCommand { get; }
    public ICommand GeoCommand { get; }
    public ICommand LayoutCommand { get; }
    public ICommand BatchCommand { get; }
    public ICommand MapOpsCommand { get; }
    public ICommand LabelAuditCommand { get; }
    public ICommand DiagnosticsCommand { get; }
    public ICommand AnalyzeLayerCommand { get; }
    public ICommand ApplyRecommendationCommand { get; }
    public ICommand UndoStyleCommand { get; }
    public ICommand ImportDataCommand { get; }
    public ICommand ZoomLayerCommand { get; }
    public ICommand LayerPropertiesCommand { get; }
    public ICommand SynchronizeLayoutCommand { get; }
    public ICommand OpenLayoutCommand { get; }
    public ICommand RefreshPreviewCommand { get; }
    public ICommand OptimizeLayoutCommand { get; }
    public ICommand ExportLayoutCommand { get; }
    public ICommand CopyReportCommand { get; }
    public ICommand SelectManifestCommand { get; }
    public ICommand CreateManifestCommand { get; }
    public ICommand ApproveLayoutCommand { get; }
    public ICommand ExportCertificateCommand { get; }
    public ICommand CommunityCommand { get; }
    public ICommand RefreshCommunityCommand { get; }

    public static void Show()
    {
        var pane = FrameworkApplication.DockPaneManager.Find(DockPaneId);
        pane?.Activate();
    }

    private void AnalyzeSelectedLayer()
    {
        if (string.IsNullOrWhiteSpace(SelectedLayerName))
        {
            RecommendationText = "Sélectionnez une couche vectorielle ou raster valide.";
            return;
        }

        if (IsRasterLayer)
            GeoprocessingService.Open("RasterIntelligence", SelectedLayerName, false);
        else
            GeoprocessingService.Open("VectorIntelligence", SelectedLayerName, 1000, false);
    }

    private void ApplyRecommendation()
    {
        if (string.IsNullOrWhiteSpace(SelectedLayerName))
        {
            RecommendationText = "Sélectionnez une couche vectorielle ou raster valide.";
            return;
        }

        if (IsRasterLayer)
            GeoprocessingService.Open("RasterIntelligence", SelectedLayerName, true);
        else
            GeoprocessingService.Open("VectorIntelligence", SelectedLayerName, 1000, true);
    }

    private async Task RefreshProjectAsync()
    {
        var state = await QueuedTask.Run(() =>
        {
            var layers = MapView.Active?.Map.GetLayersAsFlattenedList() ?? [];
            var entries = layers.Select(layer => new
            {
                layer.Name,
                Visible = layer.IsVisible,
                Raster = layer is RasterLayer,
            }).ToList();
            return new
            {
                Entries = entries,
                Visible = entries.Count(item => item.Visible),
                Invalid = 0,
            };
        });

        Application.Current.Dispatcher.Invoke(() =>
        {
            var previous = SelectedLayerName;
            LayerNames.Clear();
            _rasterLayerNames.Clear();
            foreach (var entry in state.Entries)
            {
                LayerNames.Add(entry.Name);
                if (entry.Raster)
                    _rasterLayerNames.Add(entry.Name);
            }
            SelectedLayerName = previous is not null && LayerNames.Contains(previous)
                ? previous
                : LayerNames.FirstOrDefault();
            ProjectSummary =
                $"Couches : {state.Entries.Count}\n" +
                $"Couches visibles : {state.Visible}\n" +
                $"Vecteurs : {state.Entries.Count - _rasterLayerNames.Count}\n" +
                $"Rasters : {_rasterLayerNames.Count}\n" +
                $"Couches invalides : {state.Invalid}";
        });
    }

    private static ICommand Tool(string name) =>
        new DelegateCommand(() => GeoprocessingService.Open(name));

    private static ICommand NativeCommand(string id) =>
        new DelegateCommand(() =>
        {
            if (FrameworkApplication.GetPlugInWrapper(id) is ICommand command && command.CanExecute(null))
                command.Execute(null);
        });

    private static void OpenCommunityPortal()
    {
        Process.Start(new ProcessStartInfo
        {
            FileName = "https://cartomizeplugin.com/",
            UseShellExecute = true,
        });
    }
}
