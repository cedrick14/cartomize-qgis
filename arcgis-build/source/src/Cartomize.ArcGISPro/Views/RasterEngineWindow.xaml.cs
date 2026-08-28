using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Globalization;
using System.IO;
using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Windows;
using ArcGIS.Core.CIM;
using ArcGIS.Desktop.Framework.Controls;
using ArcGIS.Desktop.Framework.Threading.Tasks;
using ArcGIS.Desktop.Mapping;
using Cartomize.ArcGISPro.Services;
using Microsoft.Win32;

namespace Cartomize.ArcGISPro.Views;

public partial class RasterEngineWindow : ProWindow, INotifyPropertyChanged
{
    private readonly RasterLayer _layer;
    private readonly List<RasterClassRow> _automaticClasses = [];
    private readonly Stack<CIMBaseLayer> _history = new();
    private CIMBaseLayer? _previewDefinition;
    private string _summaryText = "Analyse du raster…";
    private string _metadataText = string.Empty;
    private string _themeEvidenceText = "Analyse thématique en cours…";
    private string _statusText = "Prêt";
    private string _selectedThemeMode = "Détection automatique";
    private string _selectedThemeProfile = "Autre carte thématique continue";
    private string _selectedRenderMode = "Continu";
    private string _selectedPalette = "Continuous";
    private string _selectedClassificationMethod = "Quantiles de l’échantillon valide";
    private string _selectedBand = "1 · Bande 1";
    private string _redBand = "1 · Bande 1";
    private string _greenBand = "1 · Bande 1";
    private string _blueBand = "1 · Bande 1";
    private string _classCount = "5";
    private string _minimum = "0";
    private string _maximum = "1";
    private bool _expertConfirmed;
    private string _lastReportPath = string.Empty;
    private bool _busy;
    private bool _allowClose;

    internal RasterEngineWindow(RasterLayer layer)
    {
        _layer = layer;
        InitializeComponent();
        DataContext = this;
        Title = $"Analyse raster · {layer.Name}";
        Loaded += async (_, _) => await AnalyzeAsync(false);
    }

    public ObservableCollection<RasterClassRow> Classes { get; } = [];
    public ObservableCollection<NoDataCandidateRow> NoDataCandidates { get; } = [];
    public ObservableCollection<string> Bands { get; } = [];
    public IReadOnlyList<string> ThemeModes { get; } = ["Détection automatique", "Choisir manuellement"];
    public IReadOnlyList<string> ThemeProfiles { get; } = [
        "Occupation du sol", "Dynamique forestière", "Déforestation", "Dégradation forestière",
        "Changement d'occupation du sol", "NDVI / végétation", "Altitude / MNT", "Pente",
        "Température", "Précipitations", "Risque", "Probabilité", "Classification raster",
        "Image satellite RGB", "Image satellite fausses couleurs", "Autre carte thématique continue"
    ];
    public IReadOnlyList<string> RenderModes { get; } = ["Catégoriel", "Continu", "Niveaux de gris", "Composition RGB"];
    public IReadOnlyList<string> Palettes { get; } = [
        "Land Cover", "Ndvi", "Elevation", "Temperature", "Precipitation", "Risk",
        "Probability", "Slope", "Forest Dynamics", "Deforestation", "Forest Degradation",
        "Land Cover Change", "Categorical", "Population", "Water", "Continuous",
        "Diverging", "Gray"
    ];
    public IReadOnlyList<string> ClassificationMethods { get; } = ["Quantiles de l’échantillon valide", "Intervalles égaux"];

    public string SummaryText { get => _summaryText; private set => Set(ref _summaryText, value); }
    public string MetadataText { get => _metadataText; private set => Set(ref _metadataText, value); }
    public string ThemeEvidenceText { get => _themeEvidenceText; private set => Set(ref _themeEvidenceText, value); }
    public string StatusText { get => _statusText; private set => Set(ref _statusText, value); }
    public string SelectedThemeMode
    {
        get => _selectedThemeMode;
        set
        {
            if (string.Equals(_selectedThemeMode, value, StringComparison.Ordinal)) return;
            _selectedThemeMode = value;
            OnPropertyChanged();
            OnPropertyChanged(nameof(IsManualTheme));
        }
    }
    public bool IsManualTheme => string.Equals(SelectedThemeMode, "Choisir manuellement", StringComparison.Ordinal);
    public string SelectedThemeProfile { get => _selectedThemeProfile; set => Set(ref _selectedThemeProfile, value); }
    public string SelectedRenderMode { get => _selectedRenderMode; set => Set(ref _selectedRenderMode, value); }
    public string SelectedPalette { get => _selectedPalette; set => Set(ref _selectedPalette, value); }
    public string SelectedClassificationMethod { get => _selectedClassificationMethod; set => Set(ref _selectedClassificationMethod, value); }
    public string SelectedBand { get => _selectedBand; set => Set(ref _selectedBand, value); }
    public string RedBand { get => _redBand; set => Set(ref _redBand, value); }
    public string GreenBand { get => _greenBand; set => Set(ref _greenBand, value); }
    public string BlueBand { get => _blueBand; set => Set(ref _blueBand, value); }
    public string ClassCount { get => _classCount; set => Set(ref _classCount, value); }
    public string Minimum { get => _minimum; set => Set(ref _minimum, value); }
    public string Maximum { get => _maximum; set => Set(ref _maximum, value); }
    public bool ExpertConfirmed { get => _expertConfirmed; set => Set(ref _expertConfirmed, value); }

    public event PropertyChangedEventHandler? PropertyChanged;

    private async void AnalyzeClick(object sender, RoutedEventArgs e) => await AnalyzeAsync(false);
    private async void DeepAnalyzeClick(object sender, RoutedEventArgs e) => await AnalyzeAsync(true);
    private async void PreviewClick(object sender, RoutedEventArgs e) => await ApplyPlanAsync(true);
    private async void ApplyRenderingClick(object sender, RoutedEventArgs e) => await ApplyPlanAsync(false);
    private async void ApplyClassesClick(object sender, RoutedEventArgs e) => await ApplyPlanAsync(false);
    private void CloseClick(object sender, RoutedEventArgs e) => Close();

    private async Task AnalyzeAsync(bool deep)
    {
        if (_busy) return;
        _busy = true;
        StatusText = deep ? "Analyse approfondie en arrière-plan…" : "Analyse du raster…";
        try
        {
            var sample = await NativeRasterAnalysisService.AnalyzeAsync(_layer, deep, ParseInt(ClassCount, 5));
            var report = CartomizeDataService.ReportPath(deep ? "raster-engine-deep.json" : "raster-engine.json");
            LoadNativeDiagnosis(sample);
            CartomizeDataService.WriteJson(report, new
            {
                schema_version = 1,
                engine = "ArcGIS Pro SDK",
                layer = _layer.Name,
                band_count = sample.BandCount,
                width = sample.Width,
                height = sample.Height,
                nodata = sample.NoData,
                sample_count = sample.SampleCount,
                minimum = sample.Minimum,
                maximum = sample.Maximum,
                mean = sample.Mean,
                median = sample.Median,
                categorical = sample.IsCategorical,
                quantile_breaks = sample.QuantileBreaks,
                frequencies = sample.Frequencies.Select(item => new { value = item.Key, count = item.Value }).ToArray(),
            });
            _lastReportPath = report;
            StatusText = deep ? "Analyse approfondie terminée" : "Analyse terminée";
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write("Raster Engine — analyse", exception);
            StatusText = exception.Message;
        }
        finally { _busy = false; }
    }

    private void LoadNativeDiagnosis(NativeRasterSample sample)
    {
        var rasterType = sample.BandCount >= 3 ? "rgb" : sample.IsCategorical ? "categorized" : "continuous";
        SummaryText = $"Type : {rasterType}\nBandes : {sample.BandCount}\nDimensions : {sample.Width:N0} × {sample.Height:N0}\n" +
            $"Échantillon : {sample.SampleCount:N0}\nMinimum : {sample.Minimum:G15}\nMaximum : {sample.Maximum:G15}\nMédiane : {sample.Median:G15}";
        ThemeEvidenceText = sample.IsCategorical ? "Classification raster" : sample.BandCount >= 3 ? "Image satellite RGB" : "Raster continu";
        MetadataText = JsonSerializer.Serialize(new
        {
            sample.BandCount,
            sample.Width,
            sample.Height,
            sample.NoData,
            sample.SampleCount,
            sample.Minimum,
            sample.Maximum,
            sample.Mean,
            sample.Median,
        }, new JsonSerializerOptions { WriteIndented = true });
        NoDataCandidates.Clear();
        if (!string.IsNullOrWhiteSpace(sample.NoData))
            NoDataCandidates.Add(new NoDataCandidateRow(sample.NoData, "100 %", "Valeur NoData déclarée par le raster"));
        Bands.Clear();
        for (var index = 1; index <= Math.Max(1, sample.BandCount); index++) Bands.Add($"{index} · Bande {index}");
        SelectedBand = Bands.First();
        RedBand = Bands.ElementAtOrDefault(0) ?? SelectedBand;
        GreenBand = Bands.ElementAtOrDefault(1) ?? SelectedBand;
        BlueBand = Bands.ElementAtOrDefault(2) ?? SelectedBand;
        Minimum = sample.Minimum.ToString("G15", CultureInfo.InvariantCulture);
        Maximum = sample.Maximum.ToString("G15", CultureInfo.InvariantCulture);
        SelectedRenderMode = sample.BandCount >= 3 ? "Composition RGB" : sample.IsCategorical ? "Catégoriel" : "Continu";
        SelectedThemeProfile = sample.BandCount >= 3 ? "Image satellite RGB" : sample.IsCategorical ? "Classification raster" : "Autre carte thématique continue";
        SelectedPalette = sample.IsCategorical ? "Categorical" : "Continuous";
        var colors = new[] { "#1F78B4", "#33A02C", "#E31A1C", "#FF7F00", "#6A3D9A", "#B15928", "#A6CEE3", "#B2DF8A", "#FB9A99", "#FDBF6F", "#CAB2D6", "#FFFF99" };
        Classes.Clear();
        if (sample.IsCategorical)
        {
            var total = Math.Max(1, sample.Frequencies.Values.Sum());
            var index = 0;
            foreach (var entry in sample.Frequencies.OrderBy(item => item.Key).Take(64))
            {
                Classes.Add(new RasterClassRow
                {
                    Visible = true,
                    ValuesText = entry.Key.ToString("G15", CultureInfo.InvariantCulture),
                    Label = entry.Key.ToString("G15", CultureInfo.CurrentCulture),
                    Color = colors[index++ % colors.Length],
                    OpacityPercent = 100,
                    PixelCount = entry.Value,
                    Percentage = 100d * entry.Value / total,
                    Status = "détectée",
                    ShowInLegend = true,
                });
            }
        }
        else
        {
            var lower = sample.Minimum;
            var index = 0;
            foreach (var upper in sample.QuantileBreaks)
            {
                Classes.Add(new RasterClassRow
                {
                    Visible = true,
                    ValuesText = $"{lower.ToString("G15", CultureInfo.InvariantCulture)}; {upper.ToString("G15", CultureInfo.InvariantCulture)}",
                    Label = $"{lower:G5} – {upper:G5}",
                    Color = colors[index++ % colors.Length],
                    OpacityPercent = 100,
                    Status = "quantile",
                    ShowInLegend = true,
                });
                lower = upper;
            }
        }
        _automaticClasses.Clear();
        _automaticClasses.AddRange(Classes.Select(item => item.Clone()));
        ClassCount = Math.Clamp(Classes.Count, 2, 64).ToString(CultureInfo.InvariantCulture);
    }

    private void LoadDiagnosis(string report)
    {
        using var document = CartomizeDataService.ReadJson(report)
            ?? throw new InvalidOperationException("Le diagnostic Raster Engine est introuvable.");
        var root = document.RootElement;
        var diagnosis = root.TryGetProperty("diagnosis", out var value) ? value : root;
        var inference = diagnosis.TryGetProperty("inference", out var inferenceValue) ? inferenceValue : default;
        var inspection = diagnosis.TryGetProperty("inspection", out var inspectionValue) ? inspectionValue : default;

        var rasterType = CartomizeDataService.Text(diagnosis, "raster_type");
        var theme = CartomizeDataService.Text(diagnosis, "theme");
        var confidence = CartomizeDataService.Number(diagnosis, "confidence");
        var rationale = ReadStrings(inference, "rationale");
        var semantics = ReadObjects(diagnosis, "band_semantics")
            .Select(item => $"Bande {CartomizeDataService.Text(item, "band")} : {CartomizeDataService.Text(item, "role")} ({CartomizeDataService.Number(item, "confidence"):P0})");
        var indices = ReadObjects(diagnosis, "spectral_indices")
            .Select(item => $"{CartomizeDataService.Text(item, "name")} — {CartomizeDataService.Text(item, "formula")} ({CartomizeDataService.Number(item, "confidence"):P0})");
        SummaryText = string.Join(Environment.NewLine, new[]
        {
            $"Type : {rasterType}", $"Thème : {theme}", $"Confiance : {confidence:P0}",
            $"Symbologie recommandée : {CartomizeDataService.Text(inference, "recommended_renderer")}",
            "", "Diagnostic", string.Join(Environment.NewLine, rationale.Select(item => $"• {item}")),
            "", "Rôles de bandes détectés", string.Join(Environment.NewLine, semantics.Select(item => $"• {item}")),
            "", "Indices spectraux calculables", string.Join(Environment.NewLine, indices.Select(item => $"• {item}")),
        });
        ThemeEvidenceText = $"Type recommandé : {ThemeLabel(theme)} · Confiance : {confidence:P0}" +
            (rationale.Any() ? Environment.NewLine + string.Join(" ", rationale.TakeLast(3)) : string.Empty);

        NoDataCandidates.Clear();
        foreach (var item in ReadObjects(inference, "nodata_candidates"))
            NoDataCandidates.Add(new NoDataCandidateRow(
                CartomizeDataService.Number(item, "value").ToString("G15", CultureInfo.InvariantCulture),
                CartomizeDataService.Number(item, "confidence").ToString("P0", CultureInfo.CurrentCulture),
                CartomizeDataService.Text(item, "reason")));

        Classes.Clear();
        _automaticClasses.Clear();
        foreach (var item in ReadObjects(diagnosis, "classes"))
        {
            var row = RasterClassRow.FromJson(item);
            Classes.Add(row);
            _automaticClasses.Add(row.Clone());
        }
        ClassCount = Math.Max(2, Classes.Count).ToString(CultureInfo.InvariantCulture);

        Bands.Clear();
        var names = ReadStrings(inspection, "band_names").ToArray();
        var bandCount = Math.Max(1, (int)CartomizeDataService.Number(inspection, "band_count"));
        for (var index = 1; index <= bandCount; index++)
            Bands.Add($"{index} · {(index <= names.Length ? names[index - 1] : $"Bande {index}")}");
        SelectedBand = Bands.FirstOrDefault() ?? "1 · Bande 1";
        RedBand = Bands.ElementAtOrDefault(0) ?? SelectedBand;
        GreenBand = Bands.ElementAtOrDefault(1) ?? SelectedBand;
        BlueBand = Bands.ElementAtOrDefault(2) ?? SelectedBand;
        Minimum = CartomizeDataService.Number(diagnosis, "minimum").ToString("G15", CultureInfo.InvariantCulture);
        Maximum = CartomizeDataService.Number(diagnosis, "maximum", 1).ToString("G15", CultureInfo.InvariantCulture);
        SelectedRenderMode = rasterType switch
        {
            "binary" or "categorized" => "Catégoriel",
            "rgb" => "Composition RGB",
            _ => "Continu",
        };
        SelectedThemeProfile = ThemeLabel(theme);
        SelectedPalette = PaletteLabel(theme, rasterType);
        MetadataText = inspection.ValueKind == JsonValueKind.Undefined
            ? diagnosis.GetRawText()
            : JsonSerializer.Serialize(inspection, new JsonSerializerOptions { WriteIndented = true });
    }

    private async Task ApplyPlanAsync(bool preview)
    {
        if (_busy) return;
        _busy = true;
        try
        {
            if (preview && _previewDefinition is null)
                _previewDefinition = await QueuedTask.Run(() => _layer.GetDefinition());
            if (!preview)
            {
                if (_previewDefinition is not null)
                    await RestoreDefinitionAsync(_previewDefinition);
                _previewDefinition = null;
                _history.Push(await QueuedTask.Run(() => _layer.GetDefinition()));
            }

            var report = CartomizeDataService.ReportPath(preview ? "raster-engine-preview.json" : "raster-engine-style.json");
            if (string.Equals(SelectedRenderMode, "Composition RGB", StringComparison.Ordinal))
                await ApplyRgbColorizerAsync();
            else
                await NativeStyleService.ApplyRasterAsync(
                    _layer,
                    new NativeRasterStyleRequest(
                        SelectedRenderMode,
                        BandNumber(SelectedBand) - 1,
                        ParseInt(ClassCount, 5),
                        SelectedClassificationMethod,
                        ParseDouble(Minimum, 0),
                        ParseDouble(Maximum, 1),
                        Classes.Where(item => item.Visible)
                            .Select(item => new NativeRasterClassStyle(
                                item.Values().LastOrDefault(),
                                item.ShowInLegend ? item.Label : string.Empty,
                                item.Color))
                            .ToArray()));
            CartomizeDataService.WriteJson(report, new
            {
                schema_version = 1,
                engine = "ArcGIS Pro SDK",
                render_mode = SelectedRenderMode,
                palette = SelectedPalette,
                render_band = BandNumber(SelectedBand),
                classification_method = SelectedClassificationMethod,
                render_minimum = ParseDouble(Minimum, 0),
                render_maximum = ParseDouble(Maximum, 1),
                red_band = BandNumber(RedBand),
                green_band = BandNumber(GreenBand),
                blue_band = BandNumber(BlueBand),
                expert_confirmed = ExpertConfirmed,
                classes = Classes.Select(item => item.ToPayload()).ToArray(),
                preview,
                non_destructive = true,
            });
            StatusText = preview ? "Aperçu actif · pixels et NoData source inchangés." : "Symbologie appliquée · pixels du raster inchangés.";
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write("Raster Engine — symbologie", exception);
            StatusText = exception.Message;
        }
        finally { _busy = false; }
    }

    private async void CancelPreviewClick(object sender, RoutedEventArgs e)
    {
        if (_previewDefinition is null) { StatusText = "Aucun aperçu actif."; return; }
        await RestoreDefinitionAsync(_previewDefinition);
        _previewDefinition = null;
        StatusText = "Aperçu annulé; le rendu antérieur est restauré.";
    }

    private async void UndoRenderingClick(object sender, RoutedEventArgs e)
    {
        if (_previewDefinition is not null)
        {
            await RestoreDefinitionAsync(_previewDefinition);
            _previewDefinition = null;
            StatusText = "Rendu précédent restauré.";
            return;
        }
        if (_history.Count == 0) { StatusText = "Aucun rendu antérieur à restaurer."; return; }
        await RestoreDefinitionAsync(_history.Pop());
        StatusText = "Rendu précédent restauré.";
    }

    private Task RestoreDefinitionAsync(CIMBaseLayer definition)
        => QueuedTask.Run(() => _layer.SetDefinition(definition));

    private Task ApplyRgbColorizerAsync()
        => QueuedTask.Run(() =>
        {
            var definition = new RGBColorizerDefinition
            {
                RedBandIndex = Math.Max(0, BandNumber(RedBand) - 1),
                GreenBandIndex = Math.Max(0, BandNumber(GreenBand) - 1),
                BlueBandIndex = Math.Max(0, BandNumber(BlueBand) - 1),
                StretchType = RasterStretchType.MinimumMaximum,
                GammaR = 1,
                GammaG = 1,
                GammaB = 1,
            };
            if (!_layer.CanCreateColorizer(definition))
                throw new InvalidOperationException("La composition RGB n’est pas compatible avec ce raster.");
            var colorizer = _layer.CreateColorizer(definition);
            if (colorizer is CIMRasterRGBColorizer rgb)
            {
                var minimum = ParseDouble(Minimum, 0);
                var maximum = ParseDouble(Maximum, 1);
                if (maximum > minimum)
                {
                    rgb.UseCustomStretchMinMax = true;
                    rgb.CustomStretchMinRed = minimum;
                    rgb.CustomStretchMinGreen = minimum;
                    rgb.CustomStretchMinBlue = minimum;
                    rgb.CustomStretchMaxRed = maximum;
                    rgb.CustomStretchMaxGreen = maximum;
                    rgb.CustomStretchMaxBlue = maximum;
                }
            }
            _layer.SetColorizer(colorizer);
        });

    private void AddClassClick(object sender, RoutedEventArgs e)
        => Classes.Add(new RasterClassRow { ValuesText = "", Label = "Nouvelle classe", Color = "#808080", OpacityPercent = 100, Visible = true, ShowInLegend = true, Status = "visuelle" });

    private void HideClassesClick(object sender, RoutedEventArgs e)
    {
        foreach (var item in SelectedClasses()) { item.Visible = false; item.ShowInLegend = false; }
        ClassGrid.Items.Refresh();
    }

    private void DeleteClassesClick(object sender, RoutedEventArgs e)
    {
        foreach (var item in SelectedClasses().ToArray()) Classes.Remove(item);
    }

    private void ResetClassesClick(object sender, RoutedEventArgs e)
    {
        Classes.Clear();
        foreach (var item in _automaticClasses) Classes.Add(item.Clone());
        StatusText = "Analyse automatique restaurée.";
    }

    private void MoveClassUpClick(object sender, RoutedEventArgs e) => MoveSelectedClass(-1);
    private void MoveClassDownClick(object sender, RoutedEventArgs e) => MoveSelectedClass(1);

    private void MoveSelectedClass(int offset)
    {
        if (ClassGrid.SelectedItem is not RasterClassRow item) return;
        var oldIndex = Classes.IndexOf(item);
        var newIndex = Math.Clamp(oldIndex + offset, 0, Classes.Count - 1);
        if (oldIndex != newIndex) Classes.Move(oldIndex, newIndex);
    }

    private void MergeClassesClick(object sender, RoutedEventArgs e)
    {
        var selected = SelectedClasses().ToArray();
        if (selected.Length < 2) { StatusText = "Sélectionnez au moins deux classes."; return; }
        var first = selected[0];
        first.ValuesText = string.Join(", ", selected.SelectMany(item => item.Values()).Distinct().OrderBy(value => value).Select(value => value.ToString("G15", CultureInfo.InvariantCulture)));
        first.PixelCount = selected.Sum(item => item.PixelCount);
        first.Percentage = selected.Sum(item => item.Percentage);
        first.BorderPercentage = selected.Sum(item => item.BorderPercentage);
        first.Status = "fusion visuelle";
        foreach (var item in selected.Skip(1)) Classes.Remove(item);
        ClassGrid.Items.Refresh();
    }

    private void MarkNoDataClick(object sender, RoutedEventArgs e) => SetSelectedNoData(false);
    private void KeepClassClick(object sender, RoutedEventArgs e) => SetSelectedNoData(true);

    private void SetSelectedNoData(bool keep)
    {
        foreach (var candidate in NoDataGrid.SelectedItems.OfType<NoDataCandidateRow>())
        {
            if (!double.TryParse(candidate.Value, NumberStyles.Float, CultureInfo.InvariantCulture, out var value)) continue;
            var row = Classes.FirstOrDefault(item => item.Values().Any(current => Math.Abs(current - value) < 1e-12));
            if (row is null) continue;
            row.Visible = keep;
            row.ShowInLegend = keep;
            row.Status = keep ? "conservée" : "NoData visuel";
        }
        ClassGrid.Items.Refresh();
    }

    private IEnumerable<RasterClassRow> SelectedClasses() => ClassGrid.SelectedItems.OfType<RasterClassRow>();

    private void ExportDiagnosticClick(object sender, RoutedEventArgs e)
    {
        if (!File.Exists(_lastReportPath)) { StatusText = "Lancez d’abord l’analyse."; return; }
        var dialog = new SaveFileDialog { Filter = "Diagnostic Cartomize (*.json)|*.json", FileName = $"diagnostic-{SafeName(_layer.Name)}.json" };
        if (dialog.ShowDialog() != true) return;
        File.Copy(_lastReportPath, dialog.FileName, true);
        StatusText = $"Diagnostic exporté : {dialog.FileName}";
    }

    private async void SaveStyleClick(object sender, RoutedEventArgs e)
    {
        var dialog = new SaveFileDialog { Filter = "Style QGIS (*.qml)|*.qml", FileName = $"Cartomize-{SafeName(_layer.Name)}.qml" };
        if (dialog.ShowDialog() != true) return;
        await File.WriteAllTextAsync(dialog.FileName, BuildQmlStyle());
        StatusText = $"Style QML enregistré : {dialog.FileName}";
    }

    private static IEnumerable<JsonElement> ReadObjects(JsonElement root, string name)
        => root.ValueKind == JsonValueKind.Object && root.TryGetProperty(name, out var values) && values.ValueKind == JsonValueKind.Array
            ? values.EnumerateArray().ToArray()
            : [];

    private static IEnumerable<string> ReadStrings(JsonElement root, string name)
        => ReadObjects(root, name).Select(item => item.ValueKind == JsonValueKind.String ? item.GetString() ?? "" : item.ToString());

    private static int ParseInt(string text, int fallback)
        => int.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out var value) ? Math.Clamp(value, 2, 64) : fallback;

    private static double ParseDouble(string text, double fallback)
        => double.TryParse(text.Replace(',', '.'), NumberStyles.Float, CultureInfo.InvariantCulture, out var value) ? value : fallback;

    private static int BandNumber(string text)
        => int.TryParse((text ?? string.Empty).Split('·', 2)[0].Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var value) ? Math.Max(1, value) : 1;

    private static string ThemeLabel(string key) => (key ?? string.Empty).Trim().ToLowerInvariant() switch
    {
        "land_cover" => "Occupation du sol", "forest_dynamics" => "Dynamique forestière",
        "deforestation" => "Déforestation", "forest_degradation" => "Dégradation forestière",
        "land_cover_change" => "Changement d'occupation du sol", "ndvi" => "NDVI / végétation",
        "elevation" => "Altitude / MNT", "slope" => "Pente", "temperature" => "Température",
        "precipitation" => "Précipitations", "risk" => "Risque", "probability" => "Probabilité",
        "categorical" => "Classification raster", "rgb" => "Image satellite RGB",
        "false_color" => "Image satellite fausses couleurs", _ => "Autre carte thématique continue",
    };

    private static string PaletteLabel(string theme, string rasterType)
    {
        var key = string.IsNullOrWhiteSpace(theme)
            ? (rasterType is "binary" or "categorized" ? "categorical" : "continuous")
            : theme;
        return string.Join(" ", key.Split('_').Select(word => CultureInfo.InvariantCulture.TextInfo.ToTitleCase(word)));
    }

    private string BuildQmlStyle()
    {
        static string Escape(string value) => System.Security.SecurityElement.Escape(value) ?? string.Empty;
        var entries = Classes.Where(item => item.Visible).SelectMany(item => item.Values().Select(value =>
            $"<paletteEntry alpha=\"{Math.Clamp((int)Math.Round(item.OpacityPercent * 2.55), 0, 255)}\" color=\"{Escape(item.Color)}\" label=\"{Escape(item.Label)}\" value=\"{value.ToString("G15", CultureInfo.InvariantCulture)}\"/>"));
        return $"<?xml version=\"1.0\" encoding=\"UTF-8\"?><qgis version=\"3\" styleCategories=\"Symbology\"><pipe><rasterrenderer opacity=\"1\" alphaBand=\"-1\" band=\"{BandNumber(SelectedBand)}\" type=\"paletted\"><colorPalette>{string.Concat(entries)}</colorPalette></rasterrenderer></pipe></qgis>";
    }

    protected override async void OnClosing(CancelEventArgs e)
    {
        if (!_allowClose && _previewDefinition is not null)
        {
            e.Cancel = true;
            await RestoreDefinitionAsync(_previewDefinition);
            _previewDefinition = null;
            _allowClose = true;
            Close();
            return;
        }
        base.OnClosing(e);
    }

    private static string SafeName(string value)
        => string.Concat(value.Select(character => Path.GetInvalidFileNameChars().Contains(character) ? '_' : character));

    private void Set<T>(ref T field, T value, [CallerMemberName] string? name = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value)) return;
        field = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }

    private void OnPropertyChanged([CallerMemberName] string? name = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}

public sealed record NoDataCandidateRow(string Value, string Confidence, string Reason);

public sealed class RasterClassRow
{
    public bool Visible { get; set; }
    public string ValuesText { get; set; } = string.Empty;
    public string Label { get; set; } = string.Empty;
    public string Color { get; set; } = "#808080";
    public double OpacityPercent { get; set; } = 100;
    public long PixelCount { get; set; }
    public double Percentage { get; set; }
    public double BorderPercentage { get; set; }
    public string Status { get; set; } = string.Empty;
    public bool ShowInLegend { get; set; }

    public static RasterClassRow FromJson(JsonElement item)
        => new()
        {
            Visible = !item.TryGetProperty("visible", out var visible) || visible.GetBoolean(),
            ValuesText = item.TryGetProperty("values", out var values) && values.ValueKind == JsonValueKind.Array
                ? string.Join(", ", values.EnumerateArray().Select(value => value.ToString()))
                : string.Empty,
            Label = CartomizeDataService.Text(item, "label"),
            Color = CartomizeDataService.Text(item, "color", "#808080"),
            OpacityPercent = 100 * CartomizeDataService.Number(item, "opacity", 1),
            PixelCount = (long)CartomizeDataService.Number(item, "pixel_count"),
            Percentage = CartomizeDataService.Number(item, "percentage"),
            BorderPercentage = 100 * CartomizeDataService.Number(item, "border_percentage"),
            Status = CartomizeDataService.Text(item, "status"),
            ShowInLegend = !item.TryGetProperty("show_in_legend", out var legend) || legend.GetBoolean(),
        };

    public IEnumerable<double> Values()
        => ValuesText.Split([',', ';', '|'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Select(value => double.TryParse(value.Replace(',', '.'), NumberStyles.Float, CultureInfo.InvariantCulture, out var number) ? (double?)number : null)
            .Where(value => value.HasValue)
            .Select(value => value!.Value);

    public object ToPayload() => new
    {
        values = Values().ToArray(), label = Label, color = Color,
        opacity = Math.Clamp(OpacityPercent / 100.0, 0, 1), pixel_count = PixelCount,
        percentage = Percentage, border_percentage = BorderPercentage / 100.0,
        visible = Visible, status = Status, show_in_legend = ShowInLegend,
    };

    public RasterClassRow Clone() => new()
    {
        Visible = Visible, ValuesText = ValuesText, Label = Label, Color = Color,
        OpacityPercent = OpacityPercent, PixelCount = PixelCount, Percentage = Percentage,
        BorderPercentage = BorderPercentage, Status = Status, ShowInLegend = ShowInLegend,
    };
}
