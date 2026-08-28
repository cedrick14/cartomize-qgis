using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Globalization;
using System.IO;
using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Windows;
using ArcGIS.Desktop.Framework.Controls;
using ArcGIS.Desktop.Mapping;
using Cartomize.ArcGISPro.Services;
using Microsoft.Win32;

namespace Cartomize.ArcGISPro.Views;

public partial class VectorEngineWindow : ProWindow, INotifyPropertyChanged
{
    private readonly Map _map;
    private readonly string _initialPrimaryLayerId;
    private readonly string _objectiveId;
    private readonly string _objectiveLabel;
    private NativeVectorWorkspaceAnalysis? _analysis;
    private NativeVectorCompositionSnapshot? _snapshot;
    private VectorLayerRow? _primaryLayer;
    private VectorRelationRow? _selectedRelation;
    private string _summaryText = "Inventaire des couches vectorielles en cours…";
    private string _planText = "Lancez l’analyse pour construire un plan multi-couches explicable.";
    private string _statusText = "Initialisation";
    private bool _visibleOnly = true;
    private bool _reorderLayers = true;
    private bool _harmonizeStyles = true;
    private bool _enableSmartLabels = true;
    private bool _busy;
    private bool _previewActive;
    private bool _allowClose;

    internal VectorEngineWindow(
        Map map,
        BasicFeatureLayer? primaryLayer,
        string objectiveId,
        string objectiveLabel)
    {
        _map = map;
        _initialPrimaryLayerId = primaryLayer?.URI ?? string.Empty;
        _objectiveId = string.IsNullOrWhiteSpace(objectiveId) ? "auto" : objectiveId;
        _objectiveLabel = string.IsNullOrWhiteSpace(objectiveLabel) ? "Détection automatique" : objectiveLabel;
        InitializeComponent();
        DataContext = this;
        Title = $"Vector Engine · {map.Name}";
        Loaded += async (_, _) => await LoadInventoryAsync();
        Closing += OnClosing;
    }

    public ObservableCollection<VectorLayerRow> Layers { get; } = [];
    public ObservableCollection<VectorRelationRow> Relations { get; } = [];
    public ObservableCollection<NativeVectorCompositionItem> Composition { get; } = [];

    public VectorLayerRow? PrimaryLayer
    {
        get => _primaryLayer;
        set => Set(ref _primaryLayer, value);
    }

    public VectorRelationRow? SelectedRelation
    {
        get => _selectedRelation;
        set
        {
            if (!Set(ref _selectedRelation, value)) return;
            OnPropertyChanged(nameof(SelectedRelationEvidence));
        }
    }

    public string SelectedRelationEvidence => SelectedRelation is null
        ? "Sélectionnez une relation pour afficher les preuves et la sortie proposée."
        : $"{SelectedRelation.Evidence}\nSortie proposée : {SelectedRelation.ExpectedResult}" +
          (SelectedRelation.SpatialReferenceMismatch
              ? "\nAttention : les systèmes de coordonnées diffèrent ; une reprojection temporaire sera nécessaire."
              : string.Empty);

    public string SummaryText { get => _summaryText; private set => Set(ref _summaryText, value); }
    public string PlanText { get => _planText; private set => Set(ref _planText, value); }
    public string StatusText { get => _statusText; private set => Set(ref _statusText, value); }
    public bool VisibleOnly { get => _visibleOnly; set => Set(ref _visibleOnly, value); }
    public bool ReorderLayers { get => _reorderLayers; set => Set(ref _reorderLayers, value); }
    public bool HarmonizeStyles { get => _harmonizeStyles; set => Set(ref _harmonizeStyles, value); }
    public bool EnableSmartLabels { get => _enableSmartLabels; set => Set(ref _enableSmartLabels, value); }

    public event PropertyChangedEventHandler? PropertyChanged;

    private async void AnalyzeClick(object sender, RoutedEventArgs e) => await AnalyzeAsync(false);
    private async void DeepAnalyzeClick(object sender, RoutedEventArgs e) => await AnalyzeAsync(true);
    private async void PreviewCompositionClick(object sender, RoutedEventArgs e) => await ApplyCompositionAsync(false);
    private async void ApplyCompositionClick(object sender, RoutedEventArgs e) => await ApplyCompositionAsync(true);
    private async void UndoCompositionClick(object sender, RoutedEventArgs e) => await RestoreCompositionAsync();
    private void CloseClick(object sender, RoutedEventArgs e) => Close();

    private void SelectAllClick(object sender, RoutedEventArgs e)
    {
        foreach (var layer in Layers) layer.IsIncluded = true;
        StatusText = $"{Layers.Count} couche(s) sélectionnée(s).";
    }

    private void SelectVisibleClick(object sender, RoutedEventArgs e)
    {
        foreach (var layer in Layers) layer.IsIncluded = layer.IsVisible;
        PrimaryLayer = Layers.FirstOrDefault(layer => layer.IsIncluded) ?? Layers.FirstOrDefault();
        StatusText = $"{Layers.Count(layer => layer.IsIncluded)} couche(s) visible(s) sélectionnée(s).";
    }

    private void InvertSelectionClick(object sender, RoutedEventArgs e)
    {
        foreach (var layer in Layers) layer.IsIncluded = !layer.IsIncluded;
        PrimaryLayer = PrimaryLayer?.IsIncluded == true
            ? PrimaryLayer
            : Layers.FirstOrDefault(layer => layer.IsIncluded) ?? Layers.FirstOrDefault();
        StatusText = $"{Layers.Count(layer => layer.IsIncluded)} couche(s) sélectionnée(s).";
    }

    private async Task LoadInventoryAsync()
    {
        if (_busy) return;
        SetBusy(true, "Inventaire des couches vectorielles…");
        try
        {
            var descriptors = await NativeVectorWorkspaceService.InventoryAsync(_map);
            Layers.Clear();
            foreach (var descriptor in descriptors)
            {
                var selected = descriptor.IsVisible
                               || descriptor.LayerId.Equals(_initialPrimaryLayerId, StringComparison.Ordinal);
                Layers.Add(new VectorLayerRow(descriptor, selected));
            }
            PrimaryLayer = Layers.FirstOrDefault(layer => layer.Id.Equals(_initialPrimaryLayerId, StringComparison.Ordinal))
                           ?? Layers.FirstOrDefault(layer => layer.IsIncluded)
                           ?? Layers.FirstOrDefault();
            SummaryText = $"Carte : {_map.Name}\nCouches vectorielles disponibles : {Layers.Count}\n" +
                          $"Couches visibles : {Layers.Count(layer => layer.IsVisible)}\nObjectif : {_objectiveLabel}";
            StatusText = Layers.Count == 0
                ? "Aucune couche vectorielle disponible."
                : "Sélectionnez les couches, puis lancez l’analyse.";
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write("Inventaire du Vector Engine", exception);
            StatusText = $"Inventaire impossible : {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async Task AnalyzeAsync(bool deep)
    {
        if (_busy) return;
        var selected = Layers.Where(layer => layer.IsIncluded).Select(layer => layer.Id).ToArray();
        if (selected.Length == 0)
        {
            StatusText = "Sélectionnez au moins une couche vectorielle.";
            return;
        }
        PrimaryLayer = PrimaryLayer?.IsIncluded == true
            ? PrimaryLayer
            : Layers.First(layer => layer.IsIncluded);
        SetBusy(true, deep ? "Analyse approfondie des relations…" : "Analyse rapide des relations…");
        try
        {
            _analysis = await NativeVectorWorkspaceService.AnalyzeAsync(
                _map,
                selected,
                PrimaryLayer.Id,
                _objectiveId,
                VisibleOnly,
                deep);
            var profiles = _analysis.Profiles.ToDictionary(profile => profile.LayerId, StringComparer.Ordinal);
            foreach (var row in Layers)
                if (profiles.TryGetValue(row.Id, out var profile)) row.Update(profile);

            Relations.Clear();
            foreach (var relation in _analysis.Relations)
                Relations.Add(new VectorRelationRow(relation));
            SelectedRelation = Relations.FirstOrDefault(relation => relation.IntersectingFeatures > 0)
                               ?? Relations.FirstOrDefault();
            Composition.Clear();
            foreach (var item in _analysis.Composition) Composition.Add(item);
            SummaryText = _analysis.Summary;
            PlanText = _analysis.PlanText.Replace($"Objectif : {_objectiveId}", $"Objectif : {_objectiveLabel}", StringComparison.Ordinal);
            StatusText = $"Analyse terminée : {_analysis.Profiles.Count} couche(s), {_analysis.Relations.Count} relation(s).";
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write("Analyse Vector Engine multi-couches", exception);
            StatusText = $"Analyse impossible : {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async Task ApplyCompositionAsync(bool commit)
    {
        if (_busy) return;
        if (_analysis is null)
        {
            await AnalyzeAsync(false);
            if (_analysis is null) return;
        }
        SetBusy(true, commit ? "Application de la composition…" : "Prévisualisation de la composition…");
        try
        {
            _snapshot ??= await NativeVectorWorkspaceService.CaptureCompositionAsync(
                _map,
                _analysis.Profiles.Select(profile => profile.LayerId).ToArray());
            await NativeVectorWorkspaceService.ApplyCompositionAsync(
                _map,
                _analysis,
                ReorderLayers,
                HarmonizeStyles,
                EnableSmartLabels);
            _previewActive = !commit;
            StatusText = commit
                ? "Composition appliquée. Les données sources sont intactes et l’annulation reste disponible."
                : "Aperçu appliqué. Utilisez « Appliquer » pour conserver ou « Annuler » pour restaurer.";
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write("Composition Vector Engine", exception);
            StatusText = $"Composition impossible : {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async Task RestoreCompositionAsync()
    {
        if (_busy) return;
        if (_snapshot is null)
        {
            StatusText = "Aucune composition précédente n’est disponible.";
            return;
        }
        SetBusy(true, "Restauration de la composition précédente…");
        try
        {
            await NativeVectorWorkspaceService.RestoreCompositionAsync(_map, _snapshot);
            _snapshot = null;
            _previewActive = false;
            StatusText = "Symbologie et ordre des couches restaurés.";
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write("Restauration Vector Engine", exception);
            StatusText = $"Restauration impossible : {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private void ExportPlanClick(object sender, RoutedEventArgs e)
    {
        if (_analysis is null)
        {
            StatusText = "Lancez d’abord l’analyse multi-couches.";
            return;
        }
        var dialog = new SaveFileDialog
        {
            Filter = "Plan Vector Engine (*.vector-plan.json)|*.vector-plan.json|JSON (*.json)|*.json",
            FileName = $"vector-plan-{SafeName(_map.Name)}.vector-plan.json",
        };
        if (dialog.ShowDialog() != true) return;
        var payload = new
        {
            schema_version = 1,
            application = "Cartomize ArcGIS Pro 10.5.1",
            generated_utc = DateTimeOffset.UtcNow,
            objective = _objectiveId,
            objective_label = _objectiveLabel,
            analysis = _analysis,
            composition_options = new
            {
                reorder_layers = ReorderLayers,
                harmonize_styles = HarmonizeStyles,
                smart_labels = EnableSmartLabels,
            },
        };
        File.WriteAllText(dialog.FileName, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
        StatusText = $"Plan exporté : {dialog.FileName}";
    }

    private async void OnClosing(object? sender, CancelEventArgs e)
    {
        if (_allowClose || !_previewActive || _snapshot is null) return;
        e.Cancel = true;
        var decision = MessageBox.Show(
            "Une prévisualisation est encore active. Restaurer la composition précédente avant de fermer ?",
            "Vector Engine",
            MessageBoxButton.YesNoCancel,
            MessageBoxImage.Question);
        if (decision == MessageBoxResult.Cancel) return;
        if (decision == MessageBoxResult.Yes)
            await RestoreCompositionAsync();
        _allowClose = true;
        Close();
    }

    private void SetBusy(bool value, string? status = null)
    {
        _busy = value;
        if (!string.IsNullOrWhiteSpace(status)) StatusText = status;
    }

    private static string SafeName(string value)
        => string.Concat((value ?? "map").Select(character =>
            Path.GetInvalidFileNameChars().Contains(character) ? '_' : character));

    private bool Set<T>(ref T field, T value, [CallerMemberName] string? propertyName = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value)) return false;
        field = value;
        OnPropertyChanged(propertyName);
        return true;
    }

    private void OnPropertyChanged([CallerMemberName] string? propertyName = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
}

public sealed class VectorLayerRow : INotifyPropertyChanged
{
    private bool _isIncluded;
    private string _role = "À analyser";
    private double _confidence;
    private long _featureCount;
    private string _thematicField = "—";
    private string _labelField = "—";
    private string _qualityText = "Non évaluée";

    internal VectorLayerRow(NativeVectorLayerDescriptor descriptor, bool selected)
    {
        Id = descriptor.LayerId;
        Name = descriptor.Name;
        GeometryType = descriptor.GeometryType;
        IsVisible = descriptor.IsVisible;
        IsTopLevel = descriptor.IsTopLevel;
        _isIncluded = selected;
    }

    public string Id { get; }
    public string Name { get; }
    public string GeometryType { get; }
    public bool IsVisible { get; }
    public bool IsTopLevel { get; }
    public bool IsIncluded
    {
        get => _isIncluded;
        set
        {
            if (_isIncluded == value) return;
            _isIncluded = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(IsIncluded)));
        }
    }
    public string Role => _role;
    public string ConfidenceText => _confidence <= 0 ? "—" : _confidence.ToString("P0", CultureInfo.CurrentCulture);
    public string FeatureCountText => _featureCount <= 0 ? "—" : _featureCount.ToString("N0", CultureInfo.CurrentCulture);
    public string ThematicField => _thematicField;
    public string LabelField => _labelField;
    public string QualityText => _qualityText;

    internal void Update(NativeLayerProfile profile)
    {
        _role = profile.Role;
        _confidence = profile.RoleConfidence;
        _featureCount = profile.FeatureCount;
        _thematicField = string.IsNullOrWhiteSpace(profile.ThematicField) ? "—" : profile.ThematicField;
        _labelField = string.IsNullOrWhiteSpace(profile.LabelField) ? "—" : profile.LabelField;
        _qualityText = profile.Warnings.Count == 0 ? "Aucune anomalie échantillonnée" : string.Join(" · ", profile.Warnings.Take(2));
        foreach (var name in new[]
                 {
                     nameof(Role), nameof(ConfidenceText), nameof(FeatureCountText),
                     nameof(ThematicField), nameof(LabelField), nameof(QualityText),
                 })
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }

    public override string ToString() => Name;
    public event PropertyChangedEventHandler? PropertyChanged;
}

public sealed class VectorRelationRow
{
    internal VectorRelationRow(NativeVectorRelation relation)
    {
        LeftLayerName = relation.LeftLayerName;
        RightLayerName = relation.RightLayerName;
        Relation = relation.Relation;
        SuggestedOperation = relation.SuggestedOperation;
        ExpectedResult = relation.ExpectedResult;
        ExtentOverlapPercent = relation.ExtentOverlapPercent;
        SampledFeatures = relation.SampledFeatures;
        IntersectingFeatures = relation.IntersectingFeatures;
        SpatialReferenceMismatch = relation.SpatialReferenceMismatch;
        Confidence = relation.Confidence;
        Evidence = relation.Evidence;
    }

    public string LeftLayerName { get; }
    public string RightLayerName { get; }
    public string Relation { get; }
    public string SuggestedOperation { get; }
    public string ExpectedResult { get; }
    public double ExtentOverlapPercent { get; }
    public int SampledFeatures { get; }
    public int IntersectingFeatures { get; }
    public bool SpatialReferenceMismatch { get; }
    public double Confidence { get; }
    public string Evidence { get; }
    public string HitSummary => SampledFeatures <= 0 ? "—" : $"{IntersectingFeatures}/{SampledFeatures}";
    public string ConfidenceText => Confidence.ToString("P0", CultureInfo.CurrentCulture);
}
