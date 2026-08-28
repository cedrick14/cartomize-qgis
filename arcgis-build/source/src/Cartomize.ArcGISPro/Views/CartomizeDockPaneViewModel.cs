using System.Collections.ObjectModel;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Input;
using ArcGIS.Desktop.Framework;
using ArcGIS.Desktop.Framework.Contracts;
using ArcGIS.Desktop.Framework.Threading.Tasks;
using ArcGIS.Desktop.Mapping;
using Cartomize.ArcGISPro.Services;
using Microsoft.Win32;

namespace Cartomize.ArcGISPro.Views;

internal sealed class CartomizeDockPaneViewModel : DockPane
{
    private const string DockPaneId = "Cartomize_ArcGISPro_DockPane";
    private readonly HashSet<string> _rasterLayerNames = new(StringComparer.OrdinalIgnoreCase);
    private readonly List<TemplateItem> _allTemplates = [];
    private string? _selectedMapName;
    private string? _selectedLayerName;
    private ChoiceItem? _selectedObjective;
    private ChoiceItem? _selectedStyleProfile;
    private AutomationProposal? _selectedProposal;
    private TemplateItem? _selectedTemplate;
    private string _selectedTemplateCategory = "Toutes les catégories";
    private string _templateSearchText = string.Empty;
    private string? _selectedLayoutName;
    private CommunityResourceItem? _selectedCommunityResource;
    private string _projectSummary = "0 couche(s)\n0 visible(s)\n0 invalide(s)";
    private string _recommendationText = "Sélectionnez une couche vectorielle ou raster valide.";
    private string _automationReportText = "Lancez l’analyse pour obtenir une recommandation structurée.";
    private string _templateDetails = "Sélectionnez une maquette Cartomize.";
    private string _layoutTitle = "TITRE DE LA CARTE";
    private string _layoutSubtitle = string.Empty;
    private string _layoutSources = string.Empty;
    private string _layoutName = "Cartomize — Mise en page";
    private string _layoutMargin = "3";
    private string _auditScoreText = "Score non évalué";
    private string _labelAuditText = "Étiquettes non évaluées";
    private string _auditReportText = "Aucun contrôle exécuté.";
    private string _batchManifestPath = string.Empty;
    private string _mapOpsStatus = "Aucun changement vérifié.";
    private string _validationReviewer = string.Empty;
    private string _validationOrganization = string.Empty;
    private string _validationNotes = string.Empty;
    private string _validationStatus = "Statut : en attente de validation humaine";
    private string _communityStatus = "24 maquettes disponibles hors ligne.";
    private string _diagnosticText = "Diagnostic non exécuté.";
    private string _statusText = "Interface prête";
    private string _automationSources = string.Empty;
    private string _contextOpacity = "100";
    private string? _locatorMapName;
    private bool _proposalValidated;
    private string _selectedRenderMode = "Symbole unique";
    private string? _selectedThematicField;
    private string _maxClasses = "5";
    private string _selectedPalette = "Qualitative";
    private string? _selectedLabelField;
    private bool _labelsEnabled;
    private string _labelSize = "9,5";
    private string _selectedPlacement = "Automatique selon la géométrie";
    private string _layerOpacity = "100";
    private bool _confirmStyleParameters;
    private string _batchStatusText = "Sélectionnez ou créez un manifeste. Cartomize peut produire jusqu’à 5 000 cartes par série.";
    private bool _isRasterLayer;
    private bool _isBusy;
    private bool _automationVisibleOnly = true;
    private bool _automationApplySymbology;
    private bool _automationAutoCorrect = true;
    private bool _layoutVisibleOnly = true;
    private bool _layoutAddGrid;
    private bool _mapOpsAutoRegenerate;
    private bool _checkSources;
    private bool _checkCrs;
    private bool _checkSymbology;
    private bool _checkLabels;
    private bool _checkLayout;
    private bool _checkAccessibility;
    private bool _checkExport;
    private string _lastRecipeJson = string.Empty;
    private string _validationCertificateJson = string.Empty;
    private int _loadedInitializationStarted;

    protected CartomizeDockPaneViewModel()
    {
        StartupGuard.EnsureInitialized("Construction du modèle de vue Cartomize");
        StartupGuard.Stage("Initialisation des listes");
        foreach (var item in ObjectiveChoices()) Objectives.Add(item);
        foreach (var item in StyleProfileChoices()) StyleProfiles.Add(item);
        foreach (var item in new[] { "Symbole unique", "Catégorisé", "Gradué — quantiles" }) RenderModes.Add(item);
        foreach (var item in new[] { "Qualitative", "Séquentielle", "Divergente" }) PaletteChoices.Add(item);
        foreach (var item in new[] { "Automatique selon la géométrie", "Autour du point", "Sur le point", "Le long de la ligne", "Courbe", "Horizontal", "Libre" }) PlacementChoices.Add(item);
        _selectedObjective = Objectives.FirstOrDefault();
        _selectedStyleProfile = StyleProfiles.FirstOrDefault();

        StartupGuard.Stage("Initialisation des commandes");
        AnalyzeAutomationCommand = new AsyncDelegateCommand(AnalyzeAutomationAsync, () => !IsBusy);
        AutopilotCommand = new AsyncDelegateCommand(GenerateSelectedVariantAsync, () => SelectedProposal is not null && !IsBusy);
        GenerateAllCommand = new AsyncDelegateCommand(GenerateAllVariantsAsync, () => Proposals.Count > 0 && !IsBusy);
        SaveRecipeCommand = new DelegateCommand(SaveRecipe);
        ReplayCommand = new AsyncDelegateCommand(ReplayRecipeAsync, () => !IsBusy);
        AnalyzeLayerCommand = new AsyncDelegateCommand(AnalyzeSelectedLayerAsync, () => SelectedLayerName is not null && !IsBusy);
        ApplyRecommendationCommand = new AsyncDelegateCommand(ApplyRecommendationAsync, () => SelectedLayerName is not null && !IsBusy);
        UndoStyleCommand = NativeCommand("esri_core_undoButton");
        ImportDataCommand = NativeCommand("esri_mapping_addDataButton");
        ZoomLayerCommand = NativeCommand("esri_mapping_zoomToLayer");
        LayerPropertiesCommand = NativeCommand("esri_mapping_layerProperties");
        RasterCommand = new DelegateCommand(() => GeoprocessingService.Open("RasterIntelligence", SelectedLayerName ?? string.Empty, false));
        LayoutCommand = new AsyncDelegateCommand(CreateLayoutAsync, () => SelectedTemplate is not null && !IsBusy);
        SynchronizeLayoutCommand = new AsyncDelegateCommand(SynchronizeLayoutAsync, () => SelectedLayoutName is not null && !IsBusy);
        OpenLayoutCommand = NativeCommand("esri_layouts_openLayout");
        RefreshPreviewCommand = NativeCommand("esri_mapping_refreshView");
        OptimizeLayoutCommand = new AsyncDelegateCommand(OptimizeLayoutAsync, () => SelectedLayoutName is not null && !IsBusy);
        ExportPdfCommand = new AsyncDelegateCommand(() => ExportLayoutAsync("pdf"), () => SelectedLayoutName is not null && !IsBusy);
        ExportSvgCommand = new AsyncDelegateCommand(() => ExportLayoutAsync("svg"), () => SelectedLayoutName is not null && !IsBusy);
        ExportPngCommand = new AsyncDelegateCommand(() => ExportLayoutAsync("png"), () => SelectedLayoutName is not null && !IsBusy);
        ExportPagxCommand = new AsyncDelegateCommand(() => ExportLayoutAsync("pagx"), () => SelectedLayoutName is not null && !IsBusy);
        AuditCommand = new AsyncDelegateCommand(RunAuditAsync, () => !IsBusy);
        LabelAuditCommand = new AsyncDelegateCommand(RunLabelAuditAsync, () => !IsBusy);
        CopyReportCommand = new DelegateCommand(() => Clipboard.SetText(AuditReportText));
        SelectManifestCommand = new DelegateCommand(SelectManifest);
        CreateManifestCommand = new DelegateCommand(CreateManifest);
        BatchCommand = new AsyncDelegateCommand(RunBatchAsync, () => File.Exists(BatchManifestPath) && !IsBusy);
        CreateMapOpsBaselineCommand = new AsyncDelegateCommand(CreateMapOpsBaselineAsync, () => !IsBusy);
        CheckMapOpsCommand = new AsyncDelegateCommand(CheckMapOpsAsync, () => !IsBusy);
        AcceptMapOpsCommand = new AsyncDelegateCommand(AcceptMapOpsAsync, () => !IsBusy);
        RegenerateMapOpsCommand = new AsyncDelegateCommand(RegenerateAfterMapOpsAsync, () => !IsBusy);
        ApproveLayoutCommand = new DelegateCommand(ApproveLayout);
        ExportCertificateCommand = new DelegateCommand(ExportCertificate);
        RefreshCommunityCommand = new AsyncDelegateCommand(RefreshCommunityAsync, () => !IsBusy);
        OpenCommunityResourceCommand = new DelegateCommand(OpenSelectedCommunityResource);
        CommunityCommand = new DelegateCommand(() => OpenUrl("https://cartomizeplugin.com/"));
        DiagnosticsCommand = new AsyncDelegateCommand(RunDiagnosticsAsync, () => !IsBusy);
        StartupGuard.Stage("Construction du modèle de vue terminée");
    }

    public ObservableCollection<string> MapNames { get; } = [];
    public ObservableCollection<string> LayerNames { get; } = [];
    public ObservableCollection<string> LayoutNames { get; } = [];
    public ObservableCollection<string> LayerFields { get; } = [];
    public ObservableCollection<string> RenderModes { get; } = [];
    public ObservableCollection<string> PaletteChoices { get; } = [];
    public ObservableCollection<string> PlacementChoices { get; } = [];
    public ObservableCollection<ChoiceItem> Objectives { get; } = [];
    public ObservableCollection<ChoiceItem> StyleProfiles { get; } = [];
    public ObservableCollection<AutomationProposal> Proposals { get; } = [];
    public ObservableCollection<TemplateItem> FilteredTemplates { get; } = [];
    public ObservableCollection<string> TemplateCategories { get; } = [];
    public ObservableCollection<AuditFindingItem> AuditFindings { get; } = [];
    public ObservableCollection<CommunityResourceItem> CommunityResources { get; } = [];

    public string VersionText => "Cartomize 10.5.1";
    public string FooterStatus => StatusText;
    public string TemplateDetails => _templateDetails;
    public string ProjectSummary { get => _projectSummary; private set => SetProperty(ref _projectSummary, value); }
    public string RecommendationText { get => _recommendationText; private set => SetProperty(ref _recommendationText, value); }
    public string AutomationReportText { get => _automationReportText; private set => SetProperty(ref _automationReportText, value); }
    public string AutomationSources { get => _automationSources; set => SetProperty(ref _automationSources, value); }
    public string ContextOpacity { get => _contextOpacity; set => SetProperty(ref _contextOpacity, value); }
    public string? LocatorMapName { get => _locatorMapName; set => SetProperty(ref _locatorMapName, value); }
    public bool ProposalValidated { get => _proposalValidated; set => SetProperty(ref _proposalValidated, value); }
    public string SelectedRenderMode { get => _selectedRenderMode; set => SetProperty(ref _selectedRenderMode, value); }
    public string? SelectedThematicField { get => _selectedThematicField; set => SetProperty(ref _selectedThematicField, value); }
    public string MaxClasses { get => _maxClasses; set => SetProperty(ref _maxClasses, value); }
    public string SelectedPalette { get => _selectedPalette; set => SetProperty(ref _selectedPalette, value); }
    public string? SelectedLabelField { get => _selectedLabelField; set => SetProperty(ref _selectedLabelField, value); }
    public bool LabelsEnabled { get => _labelsEnabled; set => SetProperty(ref _labelsEnabled, value); }
    public string LabelSize { get => _labelSize; set => SetProperty(ref _labelSize, value); }
    public string SelectedPlacement { get => _selectedPlacement; set => SetProperty(ref _selectedPlacement, value); }
    public string LayerOpacity { get => _layerOpacity; set => SetProperty(ref _layerOpacity, value); }
    public bool ConfirmStyleParameters { get => _confirmStyleParameters; set => SetProperty(ref _confirmStyleParameters, value); }
    public string BatchStatusText { get => _batchStatusText; private set => SetProperty(ref _batchStatusText, value); }
    public string LayoutTitle { get => _layoutTitle; set => SetProperty(ref _layoutTitle, value); }
    public string LayoutSubtitle { get => _layoutSubtitle; set => SetProperty(ref _layoutSubtitle, value); }
    public string LayoutSources { get => _layoutSources; set => SetProperty(ref _layoutSources, value); }
    public string LayoutName { get => _layoutName; set => SetProperty(ref _layoutName, value); }
    public string LayoutMargin { get => _layoutMargin; set => SetProperty(ref _layoutMargin, value); }
    public string AuditScoreText { get => _auditScoreText; private set => SetProperty(ref _auditScoreText, value); }
    public string LabelAuditText { get => _labelAuditText; private set => SetProperty(ref _labelAuditText, value); }
    public string AuditReportText { get => _auditReportText; private set => SetProperty(ref _auditReportText, value); }
    public string BatchManifestPath { get => _batchManifestPath; set => SetProperty(ref _batchManifestPath, value); }
    public string MapOpsStatus { get => _mapOpsStatus; private set => SetProperty(ref _mapOpsStatus, value); }
    public string ValidationReviewer { get => _validationReviewer; set => SetProperty(ref _validationReviewer, value); }
    public string ValidationOrganization { get => _validationOrganization; set => SetProperty(ref _validationOrganization, value); }
    public string ValidationNotes { get => _validationNotes; set => SetProperty(ref _validationNotes, value); }
    public string ValidationStatus { get => _validationStatus; private set => SetProperty(ref _validationStatus, value); }
    public string CommunityStatus { get => _communityStatus; private set => SetProperty(ref _communityStatus, value); }
    public string DiagnosticText { get => _diagnosticText; private set => SetProperty(ref _diagnosticText, value); }
    public string StatusText { get => _statusText; private set { if (SetProperty(ref _statusText, value)) NotifyPropertyChanged(nameof(FooterStatus)); } }

    public string? SelectedMapName { get => _selectedMapName; set => SetProperty(ref _selectedMapName, value); }
    public ChoiceItem? SelectedObjective { get => _selectedObjective; set { if (SetProperty(ref _selectedObjective, value)) BuildProposals(); } }
    public ChoiceItem? SelectedStyleProfile { get => _selectedStyleProfile; set => SetProperty(ref _selectedStyleProfile, value); }
    public AutomationProposal? SelectedProposal { get => _selectedProposal; set { if (SetProperty(ref _selectedProposal, value)) ApplyProposalSelection(); } }
    public string? SelectedLayoutName { get => _selectedLayoutName; set => SetProperty(ref _selectedLayoutName, value); }
    public CommunityResourceItem? SelectedCommunityResource { get => _selectedCommunityResource; set => SetProperty(ref _selectedCommunityResource, value); }
    public string TemplateSearchText { get => _templateSearchText; set { if (SetProperty(ref _templateSearchText, value)) FilterTemplates(); } }
    public string SelectedTemplateCategory { get => _selectedTemplateCategory; set { if (SetProperty(ref _selectedTemplateCategory, value)) FilterTemplates(); } }
    public TemplateItem? SelectedTemplate
    {
        get => _selectedTemplate;
        set
        {
            if (!SetProperty(ref _selectedTemplate, value)) return;
            _templateDetails = value is null ? "Sélectionnez une maquette Cartomize." : $"{value.Name}\n{value.Category} · {value.PageFormat}\n\n{value.Description}";
            NotifyPropertyChanged(nameof(TemplateDetails));
        }
    }
    public string? SelectedLayerName
    {
        get => _selectedLayerName;
        set
        {
            if (!SetProperty(ref _selectedLayerName, value)) return;
            IsRasterLayer = !string.IsNullOrWhiteSpace(value) && _rasterLayerNames.Contains(value);
            RecommendationText = string.IsNullOrWhiteSpace(value) ? "Sélectionnez une couche vectorielle ou raster valide." : "Cliquez sur « Analyser la couche sélectionnée » pour obtenir une proposition.";
            _ = RefreshLayerFieldsSafelyAsync();
        }
    }

    public bool IsRasterLayer { get => _isRasterLayer; private set => SetProperty(ref _isRasterLayer, value); }
    public override bool IsBusy => _isBusy;
    public bool AutomationVisibleOnly { get => _automationVisibleOnly; set => SetProperty(ref _automationVisibleOnly, value); }
    public bool AutomationApplySymbology { get => _automationApplySymbology; set => SetProperty(ref _automationApplySymbology, value); }
    public bool AutomationAutoCorrect { get => _automationAutoCorrect; set => SetProperty(ref _automationAutoCorrect, value); }
    public bool LayoutVisibleOnly { get => _layoutVisibleOnly; set => SetProperty(ref _layoutVisibleOnly, value); }
    public bool LayoutAddGrid { get => _layoutAddGrid; set => SetProperty(ref _layoutAddGrid, value); }
    public bool MapOpsAutoRegenerate { get => _mapOpsAutoRegenerate; set => SetProperty(ref _mapOpsAutoRegenerate, value); }
    public bool CheckSources { get => _checkSources; set => SetProperty(ref _checkSources, value); }
    public bool CheckCrs { get => _checkCrs; set => SetProperty(ref _checkCrs, value); }
    public bool CheckSymbology { get => _checkSymbology; set => SetProperty(ref _checkSymbology, value); }
    public bool CheckLabels { get => _checkLabels; set => SetProperty(ref _checkLabels, value); }
    public bool CheckLayout { get => _checkLayout; set => SetProperty(ref _checkLayout, value); }
    public bool CheckAccessibility { get => _checkAccessibility; set => SetProperty(ref _checkAccessibility, value); }
    public bool CheckExport { get => _checkExport; set => SetProperty(ref _checkExport, value); }

    public ICommand AnalyzeAutomationCommand { get; }
    public ICommand AutopilotCommand { get; }
    public ICommand GenerateAllCommand { get; }
    public ICommand SaveRecipeCommand { get; }
    public ICommand ReplayCommand { get; }
    public ICommand AnalyzeLayerCommand { get; }
    public ICommand ApplyRecommendationCommand { get; }
    public ICommand UndoStyleCommand { get; }
    public ICommand ImportDataCommand { get; }
    public ICommand ZoomLayerCommand { get; }
    public ICommand LayerPropertiesCommand { get; }
    public ICommand RasterCommand { get; }
    public ICommand LayoutCommand { get; }
    public ICommand SynchronizeLayoutCommand { get; }
    public ICommand OpenLayoutCommand { get; }
    public ICommand RefreshPreviewCommand { get; }
    public ICommand OptimizeLayoutCommand { get; }
    public ICommand ExportPdfCommand { get; }
    public ICommand ExportSvgCommand { get; }
    public ICommand ExportPngCommand { get; }
    public ICommand ExportPagxCommand { get; }
    public ICommand AuditCommand { get; }
    public ICommand LabelAuditCommand { get; }
    public ICommand CopyReportCommand { get; }
    public ICommand SelectManifestCommand { get; }
    public ICommand CreateManifestCommand { get; }
    public ICommand BatchCommand { get; }
    public ICommand CreateMapOpsBaselineCommand { get; }
    public ICommand CheckMapOpsCommand { get; }
    public ICommand AcceptMapOpsCommand { get; }
    public ICommand RegenerateMapOpsCommand { get; }
    public ICommand ApproveLayoutCommand { get; }
    public ICommand ExportCertificateCommand { get; }
    public ICommand RefreshCommunityCommand { get; }
    public ICommand OpenCommunityResourceCommand { get; }
    public ICommand CommunityCommand { get; }
    public ICommand DiagnosticsCommand { get; }

    protected override Task InitializeAsync()
    {
        StartupGuard.Stage("InitializeAsync commencé");
        // ArcGIS Pro construit le contrôleur et la vue avant d'activer le DockPane.
        // Ne pas lancer QueuedTask ni modifier les collections liées pendant cette
        // phase : l'initialisation fonctionnelle démarre après l'événement Loaded.
        StartupGuard.Stage("InitializeAsync terminé — attente de la vue");
        return Task.CompletedTask;
    }

    internal async Task InitializeAfterViewLoadedAsync()
    {
        if (Interlocked.CompareExchange(ref _loadedInitializationStarted, 1, 0) != 0)
            return;

        StartupGuard.Stage("Initialisation après affichage commencée");
        try
        {
            LoadTemplateCatalog();
            StartupGuard.Stage("Catalogue des maquettes chargé");
            await RefreshProjectSafelyAsync();
            StartupGuard.Stage("Projet ArcGIS Pro actualisé");
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write("Initialisation du dockpane Cartomize", exception);
            await SetStatusSafelyAsync($"Initialisation incomplète : {exception.Message}");
        }
        finally
        {
            StartupGuard.Stage("Initialisation après affichage terminée");
        }
    }

    protected override void OnActivate(bool isActive)
    {
        StartupGuard.Stage(isActive ? "Dockpane activé par ArcGIS Pro" : "Dockpane désactivé par ArcGIS Pro");
        base.OnActivate(isActive);
    }

    public static void Show()
    {
        StartupGuard.Stage("DockPaneManager.Find appelé");
        var pane = FrameworkApplication.DockPaneManager.Find(DockPaneId)
                   ?? throw new InvalidOperationException(
                       "Le panneau Cartomize n’a pas pu être créé par ArcGIS Pro.");
        StartupGuard.Stage("Dockpane trouvé, activation demandée");
        pane.Activate();
        StartupGuard.Stage("Appel d’activation du dockpane terminé");
    }

    private async Task AnalyzeAutomationAsync()
    {
        var path = CartomizeDataService.ReportPath("automation-analysis.json");
        var result = await RunToolAsync("GeoIntelligence", SelectedMapName ?? string.Empty, path);
        if (!result.Succeeded) return;
        using var document = CartomizeDataService.ReadJson(path);
        if (document is not null)
        {
            var root = document.RootElement;
            var recommendations = root.TryGetProperty("recommendations", out var items) ? string.Join("\n", items.EnumerateArray().Select(item => $"• {item.GetString()}")) : "Analyse terminée.";
            AutomationReportText = $"Carte : {CartomizeDataService.Text(root, "map")}\n{recommendations}";
        }
        BuildProposals();
    }

    private async Task GenerateSelectedVariantAsync()
    {
        if (SelectedProposal is not null) await ExecuteAutopilotAsync(SelectedProposal, "autopilot-selected.json");
    }

    private async Task GenerateAllVariantsAsync()
    {
        var summaries = new List<string>();
        foreach (var proposal in Proposals.ToArray())
        {
            var success = await ExecuteAutopilotAsync(proposal, $"autopilot-{proposal.VariantId}.json");
            summaries.Add($"{proposal.Name} : {(success ? "créée" : "échec")}");
            if (!success) break;
        }
        AutomationReportText = string.Join("\n", summaries);
    }

    private async Task<bool> ExecuteAutopilotAsync(AutomationProposal proposal, string reportName)
    {
        var report = CartomizeDataService.ReportPath(reportName);
        var result = await RunToolAsync("AutopilotMap", SelectedMapName ?? string.Empty, SelectedObjective?.Label ?? "Détection automatique", SelectedLayerName ?? string.Empty,
            SelectedStyleProfile?.Label ?? "Équilibré", proposal.Name, AutomationApplySymbology, AutomationAutoCorrect, AutomationVisibleOnly,
            AutomationSources, LayoutTitle, proposal.TemplateName, report, ParseInt(ContextOpacity, 100, 0, 100), LocatorMapName ?? string.Empty, ProposalValidated);
        if (!result.Succeeded) return false;
        using var document = CartomizeDataService.ReadJson(report);
        if (document is not null && document.RootElement.TryGetProperty("recipe", out var recipe)) _lastRecipeJson = recipe.GetRawText();
        return true;
    }

    private void SaveRecipe()
    {
        var dialog = new SaveFileDialog { Filter = "Recette Cartomize (*.cartomize.json)|*.cartomize.json|JSON (*.json)|*.json", FileName = "recette.cartomize.json" };
        if (dialog.ShowDialog() != true) return;
        File.WriteAllText(dialog.FileName, string.IsNullOrWhiteSpace(_lastRecipeJson) ? BuildCurrentRecipeJson() : _lastRecipeJson);
        StatusText = $"Recette enregistrée : {dialog.FileName}";
    }

    private async Task ReplayRecipeAsync()
    {
        var dialog = new OpenFileDialog { Filter = "Recette Cartomize (*.cartomize.json;*.json)|*.cartomize.json;*.json" };
        if (dialog.ShowDialog() == true) await RunToolAsync("ReplayRecipe", dialog.FileName);
    }

    private async Task AnalyzeSelectedLayerAsync()
    {
        if (string.IsNullOrWhiteSpace(SelectedLayerName)) return;
        var path = CartomizeDataService.ReportPath(IsRasterLayer ? "raster-analysis.json" : "vector-analysis.json");
        var result = IsRasterLayer ? await RunToolAsync("RasterIntelligence", SelectedLayerName, false, path) : await RunToolAsync("VectorIntelligence", SelectedLayerName, 1000, false, path);
        if (!result.Succeeded) return;
        using var document = CartomizeDataService.ReadJson(path);
        if (document is null) return;
        var root = document.RootElement;
        if (IsRasterLayer && root.TryGetProperty("diagnosis", out var diagnosis))
        {
            RecommendationText = $"Type : {CartomizeDataService.Text(diagnosis, "raster_type")}\nThème : {CartomizeDataService.Text(diagnosis, "theme")}\nConfiance : {CartomizeDataService.Number(diagnosis, "confidence"):P0}";
            var rasterType = CartomizeDataService.Text(diagnosis, "raster_type");
            SelectedRenderMode = rasterType is "binary" or "categorized" ? "Catégorisé" : rasterType == "rgb" ? "Symbole unique" : "Gradué — quantiles";
            if (diagnosis.TryGetProperty("classes", out var classes) && classes.ValueKind == JsonValueKind.Array)
                MaxClasses = Math.Clamp(classes.GetArrayLength(), 2, 12).ToString(System.Globalization.CultureInfo.InvariantCulture);
            if (diagnosis.TryGetProperty("inference", out var inference))
            {
                var palette = CartomizeDataService.Text(inference, "recommended_palette");
                SelectedPalette = palette.Contains("diverg", StringComparison.OrdinalIgnoreCase) ? "Divergente" : palette.Contains("sequent", StringComparison.OrdinalIgnoreCase) ? "Séquentielle" : "Qualitative";
            }
            LabelsEnabled = false;
        }
        else if (root.TryGetProperty("profile", out var profile))
        {
            RecommendationText = $"Rôle : {CartomizeDataService.Text(profile, "role")}\nÉtiquette : {CartomizeDataService.Text(profile, "label_field", "à confirmer")}\nChamp thématique : {CartomizeDataService.Text(profile, "thematic_field", "à confirmer")}";
            SelectedThematicField = CartomizeDataService.Text(profile, "thematic_field");
            SelectedLabelField = CartomizeDataService.Text(profile, "label_field");
            LabelsEnabled = !string.IsNullOrWhiteSpace(SelectedLabelField);
            var role = "";
            if (profile.TryGetProperty("fields", out var fields) && fields.ValueKind == JsonValueKind.Array)
            {
                foreach (var field in fields.EnumerateArray())
                    if (CartomizeDataService.Text(field, "name").Equals(SelectedThematicField, StringComparison.OrdinalIgnoreCase))
                    { role = CartomizeDataService.Text(field, "semantic_role"); break; }
            }
            SelectedRenderMode = role is "category" or "coded_category" or "ordinal" ? "Catégorisé" : string.IsNullOrWhiteSpace(SelectedThematicField) ? "Symbole unique" : "Gradué — quantiles";
            SelectedPalette = SelectedRenderMode == "Catégorisé" ? "Qualitative" : role == "diverging_quantitative" ? "Divergente" : "Séquentielle";
        }
        ConfirmStyleParameters = false;
    }

    private async Task ApplyRecommendationAsync()
    {
        if (string.IsNullOrWhiteSpace(SelectedLayerName)) return;
        var report = CartomizeDataService.ReportPath(IsRasterLayer ? "raster-style.json" : "vector-style.json");
        var classes = ParseInt(MaxClasses, 5, 2, 12);
        var labelSize = ParseDouble(LabelSize, 9.5, 5, 48);
        var opacity = ParseInt(LayerOpacity, 100, 0, 100);
        if (IsRasterLayer)
            await RunToolAsync("RasterIntelligence", SelectedLayerName, true, report, SelectedRenderMode, SelectedThematicField ?? string.Empty, classes, SelectedPalette, SelectedLabelField ?? string.Empty, LabelsEnabled, labelSize, SelectedPlacement, opacity, ConfirmStyleParameters);
        else
            await RunToolAsync("VectorIntelligence", SelectedLayerName, 1000, true, report, SelectedRenderMode, SelectedThematicField ?? string.Empty, classes, SelectedPalette, SelectedLabelField ?? string.Empty, LabelsEnabled, labelSize, SelectedPlacement, opacity, ConfirmStyleParameters);
    }

    private async Task CreateLayoutAsync() => await ExecuteLayoutAsync("Créer", string.Empty);
    private async Task SynchronizeLayoutAsync() => await ExecuteLayoutAsync("Synchroniser", string.Empty);
    private async Task OptimizeLayoutAsync() => await ExecuteLayoutAsync("Optimiser", string.Empty);

    private async Task ExportLayoutAsync(string extension)
    {
        var dialog = new SaveFileDialog { Filter = $"{extension.ToUpperInvariant()} (*.{extension})|*.{extension}", FileName = $"carte.{extension}" };
        if (dialog.ShowDialog() == true) await ExecuteLayoutAsync("Exporter", dialog.FileName);
    }

    private async Task ExecuteLayoutAsync(string operation, string exportPath)
    {
        if (SelectedTemplate is null) return;
        _ = double.TryParse(LayoutMargin.Replace(',', '.'), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var margin);
        await RunToolAsync("CreateLayout", SelectedMapName ?? string.Empty, SelectedTemplate.Label, LayoutTitle, LayoutSubtitle, LayoutName, LayoutSources, LayoutVisibleOnly,
            margin <= 0 ? 3.0 : margin, LayoutAddGrid, true, operation == "Créer", exportPath, 600,
            exportPath.EndsWith(".pagx", StringComparison.OrdinalIgnoreCase) ? exportPath : string.Empty, string.Empty, operation, SelectedLayoutName ?? string.Empty,
            ParseInt(ContextOpacity, 100, 0, 100), LocatorMapName ?? string.Empty);
        await RefreshProjectAsync();
    }

    private async Task RunAuditAsync()
    {
        var report = CartomizeDataService.ReportPath("audit.json");
        var result = await RunToolAsync("AuditProject", report, "Projet");
        if (!result.Succeeded) return;
        using var document = CartomizeDataService.ReadJson(report);
        if (document is not null) LoadAudit(document.RootElement);
    }

    private async Task RunLabelAuditAsync()
    {
        var report = CartomizeDataService.ReportPath("labels.json");
        var result = await RunToolAsync("AuditProject", report, "Étiquettes");
        if (!result.Succeeded) return;
        using var document = CartomizeDataService.ReadJson(report);
        if (document is null) return;
        LabelAuditText = CartomizeDataService.Text(document.RootElement, "status", "Étiquettes contrôlées");
        LoadAudit(document.RootElement);
    }

    private void LoadAudit(JsonElement root)
    {
        AuditScoreText = $"{CartomizeDataService.Number(root, "score"):0}/100 — {CartomizeDataService.Text(root, "status")}";
        AuditFindings.Clear();
        if (root.TryGetProperty("findings", out var findings))
            foreach (var item in findings.EnumerateArray()) AuditFindings.Add(new AuditFindingItem(CartomizeDataService.Text(item, "severity"), CartomizeDataService.Text(item, "code"),
                CartomizeDataService.Text(item, "layer_name"), CartomizeDataService.Text(item, "message"), CartomizeDataService.Text(item, "remediation")));
        AuditReportText = string.Join("\n", AuditFindings.Select(item => $"[{item.Severity}] {item.Code} — {item.Message} {item.Remediation}"));
    }

    private void SelectManifest()
    {
        var dialog = new OpenFileDialog { Filter = "Manifeste Cartomize (*.json)|*.json" };
        if (dialog.ShowDialog() == true) BatchManifestPath = dialog.FileName;
    }

    private void CreateManifest()
    {
        var dialog = new SaveFileDialog { Filter = "Manifeste Cartomize (*.json)|*.json", FileName = "manifeste-cartomize.json" };
        if (dialog.ShowDialog() != true) return;
        var recipePath = Path.ChangeExtension(dialog.FileName, ".cartomize.json");
        File.WriteAllText(recipePath, string.IsNullOrWhiteSpace(_lastRecipeJson) ? BuildCurrentRecipeJson() : _lastRecipeJson);
        CartomizeDataService.WriteJson(dialog.FileName, new { schema_version = 1, recipe_path = recipePath,
            output_directory = Path.Combine(Path.GetDirectoryName(dialog.FileName)!, "exports"), dpi = 600, keep_layouts = false, require_human_validation = true,
            jobs = new[] { new { job_id = "carte-001", output_name = "carte-001", title = LayoutTitle, subtitle = LayoutSubtitle, sources = LayoutSources, output_formats = new[] { "pdf", "png" } } } });
        BatchManifestPath = dialog.FileName;
        StatusText = "Manifeste créé.";
    }

    private async Task RunBatchAsync()
    {
        var result = await RunToolAsync("BatchMaps", BatchManifestPath, CartomizeDataService.ReportPath("batch-report.json"));
        BatchStatusText = result.Succeeded ? "Série terminée. Consultez le rapport de production." : result.Messages;
    }
    private string MapOpsPath => CartomizeDataService.ReportPath("mapops-baseline.json");
    private async Task CreateMapOpsBaselineAsync() => await RunMapOpsAsync("Créer référence", string.Empty, MapOpsPath);
    private async Task CheckMapOpsAsync() => await RunMapOpsAsync("Vérifier", MapOpsPath, CartomizeDataService.ReportPath("mapops-current.json"));
    private async Task AcceptMapOpsAsync() => await RunMapOpsAsync("Accepter", MapOpsPath, MapOpsPath);

    private async Task RunMapOpsAsync(string action, string previous, string output)
    {
        var result = await RunToolAsync("MapOpsCheck", previous, output, CartomizeDataService.ReportPath("mapops-report.json"), action);
        MapOpsStatus = result.Succeeded ? (string.IsNullOrWhiteSpace(result.Messages) ? action : result.Messages) : result.Messages;
    }

    private async Task RegenerateAfterMapOpsAsync()
    {
        if (!MapOpsAutoRegenerate) { StatusText = "Activez la régénération automatique avant de rejouer la recette."; return; }
        await ReplayRecipeAsync();
        ValidationStatus = "Statut : une nouvelle validation humaine est requise";
    }

    private void ApproveLayout()
    {
        if (new[] { CheckSources, CheckCrs, CheckSymbology, CheckLabels, CheckLayout, CheckAccessibility, CheckExport }.Any(value => !value)) { ValidationStatus = "Statut : checklist incomplète"; return; }
        if (string.IsNullOrWhiteSpace(ValidationReviewer)) { ValidationStatus = "Statut : nom du réviseur requis"; return; }
        var payload = new { schema_version = 1, plugin = "Cartomize", version = "10.5.1", layout = SelectedLayoutName ?? LayoutName,
            reviewer = ValidationReviewer.Trim(), organization = ValidationOrganization.Trim(), notes = ValidationNotes.Trim(),
            approved_at = DateTimeOffset.UtcNow.ToString("O"), checks = new[] { "sources", "crs", "symbology", "labels", "layout", "accessibility", "export" } };
        var json = JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true });
        var digest = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(json))).ToLowerInvariant();
        _validationCertificateJson = json.TrimEnd('}', '\r', '\n', ' ') + $",\n  \"sha256\": \"{digest}\"\n}}";
        ValidationStatus = $"Statut : approuvée par {ValidationReviewer.Trim()}";
    }

    private void ExportCertificate()
    {
        if (string.IsNullOrWhiteSpace(_validationCertificateJson)) { ValidationStatus = "Statut : approuvez d’abord la mise en page"; return; }
        var dialog = new SaveFileDialog { Filter = "Certificat Cartomize (*.json)|*.json", FileName = "certificat-cartomize.json" };
        if (dialog.ShowDialog() == true) File.WriteAllText(dialog.FileName, _validationCertificateJson);
    }

    private async Task RefreshCommunityAsync()
    {
        SetBusy(true);
        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(12) };
            client.DefaultRequestHeaders.UserAgent.ParseAdd("Cartomize-ArcGISPro/10.5.1");
            var json = await client.GetStringAsync("https://cartomizeplugin.com/api/templates/?type=layout&ordering=recent");
            using var document = JsonDocument.Parse(json);
            var values = document.RootElement.ValueKind == JsonValueKind.Array ? document.RootElement : document.RootElement.GetProperty("results");
            CommunityResources.Clear();
            foreach (var item in values.EnumerateArray().Take(200))
            {
                var id = item.TryGetProperty("id", out var idValue) && idValue.TryGetInt32(out var number) ? number : 0;
                if (id <= 0) continue;
                CommunityResources.Add(new CommunityResourceItem(id, CartomizeDataService.Text(item, "title"), CartomizeDataService.Text(item, "description"),
                    CartomizeDataService.Text(item, "category"), CartomizeDataService.Text(item, "page_format"), $"https://cartomizeplugin.com/galerie/{id}/"));
            }
            SelectedCommunityResource = CommunityResources.FirstOrDefault();
            CommunityStatus = $"{CommunityResources.Count} ressource(s) en ligne · 24 maquettes hors ligne";
        }
        catch (Exception exception) { CommunityStatus = $"Catalogue en ligne indisponible. Les 24 maquettes hors ligne restent accessibles. {exception.Message}"; }
        finally { SetBusy(false); }
    }

    private void OpenSelectedCommunityResource() { if (SelectedCommunityResource is not null) OpenUrl(SelectedCommunityResource.DetailUrl); }

    private async Task RunDiagnosticsAsync()
    {
        await RefreshProjectAsync();
        var toolbox = File.Exists(Module.ToolboxPath);
        var templates = _allTemplates.Count;
        DiagnosticText = $"Cartomize 10.5.1\nArcGIS Pro SDK 3.7\n.NET 10\n\nBoîte à outils : {(toolbox ? "disponible" : "indisponible")}\nAlgorithmes Cartomize : 9\n" +
            $"Maquettes : {templates}/24\nCartes : {MapNames.Count}\nCouches : {LayerNames.Count}\nMises en page : {LayoutNames.Count}\n\nStatut général : {(toolbox && templates == 24 ? "Conforme" : "Non conforme")}";
        StatusText = "Système vérifié";
    }

    private async Task<GeoprocessingService.ExecutionResult> RunToolAsync(string name, params object?[] values)
    {
        SetBusy(true);
        StatusText = $"Exécution : {name}";
        try
        {
            var result = await GeoprocessingService.ExecuteAsync(name, values);
            StatusText = result.Succeeded ? (string.IsNullOrWhiteSpace(result.Messages) ? "Opération terminée" : result.Messages) : $"Erreur : {result.Messages}";
            return result;
        }
        catch (Exception exception)
        {
            StatusText = $"Erreur : {exception.Message}";
            return new GeoprocessingService.ExecutionResult(false, string.Empty, exception.Message, -1);
        }
        finally { SetBusy(false); }
    }

    private async Task RefreshProjectAsync()
    {
        var state = await QueuedTask.Run(() =>
        {
            var maps = ArcGIS.Desktop.Core.Project.Current?.GetItems<ArcGIS.Desktop.Mapping.MapProjectItem>().Select(item => item.Name).ToArray() ?? [];
            var layouts = ArcGIS.Desktop.Core.Project.Current?.GetItems<ArcGIS.Desktop.Layouts.LayoutProjectItem>().Select(item => item.Name).ToArray() ?? [];
            var layers = MapView.Active?.Map.GetLayersAsFlattenedList() ?? [];
            var entries = layers.Select(layer => new { layer.Name, Visible = layer.IsVisible, Raster = layer is RasterLayer }).ToArray();
            return new { Maps = maps, Layouts = layouts, Entries = entries };
        });
        await Application.Current.Dispatcher.InvokeAsync(() =>
        {
            Replace(MapNames, state.Maps);
            Replace(LayoutNames, state.Layouts);
            var oldLayer = SelectedLayerName;
            LayerNames.Clear();
            _rasterLayerNames.Clear();
            foreach (var entry in state.Entries) { LayerNames.Add(entry.Name); if (entry.Raster) _rasterLayerNames.Add(entry.Name); }
            SelectedMapName = MapNames.Contains(SelectedMapName ?? string.Empty) ? SelectedMapName : MapNames.FirstOrDefault();
            LocatorMapName = MapNames.Contains(LocatorMapName ?? string.Empty) ? LocatorMapName : MapNames.FirstOrDefault();
            SelectedLayoutName = LayoutNames.Contains(SelectedLayoutName ?? string.Empty) ? SelectedLayoutName : LayoutNames.FirstOrDefault();
            SelectedLayerName = oldLayer is not null && LayerNames.Contains(oldLayer) ? oldLayer : LayerNames.FirstOrDefault();
            ProjectSummary = $"Couches : {state.Entries.Length}\nCouches visibles : {state.Entries.Count(item => item.Visible)}\nVecteurs : {state.Entries.Length - _rasterLayerNames.Count}\nRasters : {_rasterLayerNames.Count}\nCouches invalides : 0";
            BuildProposals();
        });
    }

    private async Task RefreshProjectSafelyAsync()
    {
        try
        {
            await RefreshProjectAsync();
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write("Initialisation du projet ArcGIS Pro", exception);
            await SetStatusSafelyAsync($"Projet ArcGIS Pro indisponible : {exception.Message}");
        }
    }

    private async Task RefreshLayerFieldsAsync()
    {
        var selected = SelectedLayerName;
        var fields = await QueuedTask.Run(() =>
        {
            if (string.IsNullOrWhiteSpace(selected)) return Array.Empty<string>();
            var layer = MapView.Active?.Map.GetLayersAsFlattenedList().FirstOrDefault(item => item.Name.Equals(selected, StringComparison.OrdinalIgnoreCase));
            if (layer is not BasicFeatureLayer basicLayer) return Array.Empty<string>();
            using var table = basicLayer.GetTable();
            using var definition = table.GetDefinition();
            return definition.GetFields().Select(field => field.Name).ToArray();
        });
        await Application.Current.Dispatcher.InvokeAsync(() =>
        {
            Replace(LayerFields, fields);
            SelectedThematicField = LayerFields.Contains(SelectedThematicField ?? string.Empty) ? SelectedThematicField : LayerFields.FirstOrDefault();
            SelectedLabelField = LayerFields.Contains(SelectedLabelField ?? string.Empty) ? SelectedLabelField : LayerFields.FirstOrDefault();
        });
    }

    private async Task RefreshLayerFieldsSafelyAsync()
    {
        try
        {
            await RefreshLayerFieldsAsync();
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write("Lecture des champs de la couche", exception);
            await SetStatusSafelyAsync($"Champs de la couche indisponibles : {exception.Message}");
        }
    }

    private async Task SetStatusSafelyAsync(string status)
    {
        try
        {
            var dispatcher = Application.Current?.Dispatcher;
            if (dispatcher is null || dispatcher.HasShutdownStarted || dispatcher.HasShutdownFinished)
                return;
            await dispatcher.InvokeAsync(() => StatusText = status);
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write("Mise à jour de l’état du panneau", exception);
        }
    }

    private void SetBusy(bool value)
    {
        if (_isBusy == value)
            return;
        _isBusy = value;
        NotifyPropertyChanged(nameof(IsBusy));
    }

    private void LoadTemplateCatalog()
    {
        try
        {
            _allTemplates.AddRange(CartomizeDataService.LoadTemplates());
            foreach (var category in new[] { "Toutes les catégories" }.Concat(_allTemplates.Select(item => item.Category).Distinct(StringComparer.CurrentCultureIgnoreCase).OrderBy(value => value))) TemplateCategories.Add(category);
            FilterTemplates();
        }
        catch (Exception exception) { StatusText = $"Catalogue de maquettes indisponible : {exception.Message}"; }
    }

    private void FilterTemplates()
    {
        var needle = TemplateSearchText.Trim();
        var values = _allTemplates.Where(item => (SelectedTemplateCategory == "Toutes les catégories" || item.Category.Equals(SelectedTemplateCategory, StringComparison.CurrentCultureIgnoreCase)) &&
            (needle.Length == 0 || $"{item.Name} {item.Category} {item.Description}".Contains(needle, StringComparison.CurrentCultureIgnoreCase)));
        Replace(FilteredTemplates, values);
        SelectedTemplate = FilteredTemplates.Contains(SelectedTemplate) ? SelectedTemplate : FilteredTemplates.FirstOrDefault();
    }

    private void BuildProposals()
    {
        if (_allTemplates.Count == 0) return;
        var objective = SelectedObjective?.Id ?? "auto";
        var preferred = objective switch
        {
            "occupation_sol" => "occupation_sol/institutionnel", "environnement" => "environnement/fragmentation-forestiere-a3",
            "transport" => "transport/accessibilite-reseau-a4", "sante" => "sante/couverture-services-a4", "agriculture" => "agriculture/aptitude-agricole-a3",
            "humanitaire" => "humanitaire/situation-urgence-a3", "biodiversite" => "biodiversite/connectivite-ecologique-a4", _ => "administrative/institutionnel",
        };
        TemplateItem Get(string id) => _allTemplates.FirstOrDefault(item => item.Id == id) ?? _allTemplates[0];
        var options = new[] { ("institutional", "Institutionnelle", Get(preferred), 3d, objective is "topographique" or "atlas"),
            ("analytical", "Analytique", Get("professionnelles/13-planche-analyse-multi-blocs"), 4d, false),
            ("minimal", "Minimaliste", Get("professionnelles/03-localisation-hierarchique"), 5d, false) };
        Proposals.Clear();
        var score = 92;
        foreach (var option in options) { Proposals.Add(new AutomationProposal(option.Item1, option.Item2, option.Item3.Id, option.Item3.Name, option.Item3.PageFormat, option.Item4, option.Item5,
            $"Marge {option.Item4:0}% · grille {(option.Item5 ? "oui" : "non")}") { Score = score }); score -= 4; }
        SelectedProposal = Proposals.FirstOrDefault();
    }

    private void ApplyProposalSelection()
    {
        if (SelectedProposal is null) return;
        SelectedTemplate = _allTemplates.FirstOrDefault(item => item.Id == SelectedProposal.TemplateId) ?? SelectedTemplate;
        LayoutMargin = SelectedProposal.MarginPercent.ToString("0.##", System.Globalization.CultureInfo.InvariantCulture);
        LayoutAddGrid = SelectedProposal.AddGrid;
    }

    private string BuildCurrentRecipeJson() => JsonSerializer.Serialize(new
    {
        schema_version = 1, source_application = "Cartomize ArcGIS Pro", plugin_version = "10.5.1", objective = SelectedObjective?.Id ?? "auto",
        visible_only = AutomationVisibleOnly, sources = AutomationSources,
        layout = new { map_name = SelectedMapName, template_id = SelectedProposal?.TemplateId ?? SelectedTemplate?.Id, layout_name = LayoutName, title = LayoutTitle,
            subtitle = LayoutSubtitle, credits = LayoutSources, margin_percent = double.TryParse(LayoutMargin, out var margin) ? margin : 3, add_grid = LayoutAddGrid,
            remove_basemap_from_legend = true, open_view = true, dpi = 600, context_opacity_percent = ParseInt(ContextOpacity, 100, 0, 100),
            locator_map_name = LocatorMapName, proposal_validated = ProposalValidated }
    }, new JsonSerializerOptions { WriteIndented = true });

    private static ICommand NativeCommand(string id) => new DelegateCommand(() =>
    {
        if (FrameworkApplication.GetPlugInWrapper(id) is ICommand command && command.CanExecute(null)) command.Execute(null);
    });

    private static void OpenUrl(string url) => Process.Start(new ProcessStartInfo { FileName = url, UseShellExecute = true });
    private static void Replace<T>(ObservableCollection<T> target, IEnumerable<T> values) { target.Clear(); foreach (var value in values) target.Add(value); }

    private static int ParseInt(string value, int fallback, int minimum, int maximum)
        => Math.Clamp(int.TryParse(value, System.Globalization.NumberStyles.Integer, System.Globalization.CultureInfo.CurrentCulture, out var parsed) ? parsed : fallback, minimum, maximum);

    private static double ParseDouble(string value, double fallback, double minimum, double maximum)
    {
        var normalized = (value ?? string.Empty).Replace(',', '.');
        var parsed = double.TryParse(normalized, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var result) ? result : fallback;
        return Math.Clamp(parsed, minimum, maximum);
    }

    private static IEnumerable<ChoiceItem> ObjectiveChoices() => new[]
    {
        new ChoiceItem("auto", "Détection automatique"), new ChoiceItem("administrative", "Carte administrative"), new ChoiceItem("amenagement", "Aménagement du territoire"),
        new ChoiceItem("occupation_sol", "Occupation du sol"), new ChoiceItem("risques", "Carte de risques"), new ChoiceItem("hydrologique", "Hydrologie"),
        new ChoiceItem("environnement", "Environnement"), new ChoiceItem("agriculture", "Agriculture"), new ChoiceItem("transport", "Transport et accessibilité"),
        new ChoiceItem("urbanisme", "Urbanisme"), new ChoiceItem("demographie", "Démographie"), new ChoiceItem("biodiversite", "Biodiversité"),
        new ChoiceItem("energie", "Énergie"), new ChoiceItem("sante", "Santé"), new ChoiceItem("humanitaire", "Humanitaire"),
        new ChoiceItem("scientifique", "Publication scientifique"), new ChoiceItem("topographique", "Topographie"), new ChoiceItem("atlas", "Atlas territorial")
    };

    private static IEnumerable<ChoiceItem> StyleProfileChoices() => new[]
    {
        new ChoiceItem("balanced", "Équilibré"), new ChoiceItem("institutional", "Institutionnel"),
        new ChoiceItem("analytical", "Analytique"), new ChoiceItem("minimal", "Minimaliste")
    };
}
