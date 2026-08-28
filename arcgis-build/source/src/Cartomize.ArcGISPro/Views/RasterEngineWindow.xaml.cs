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
    private readonly Stack<bool> _outlineHistory = new();
    private readonly HashSet<double> _selectedNoDataValues = [];
    private readonly HashSet<double> _declaredNoDataValues = [];
    private CIMBaseLayer? _previewDefinition;
    private NativeRasterSample? _lastSample;
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
    private string _outlineWidth = "1.2";
    private bool _maskNoDataAutomatically = true;
    private bool _addBlackOutline;
    private bool _expertConfirmed;
    private string _lastReportPath = string.Empty;
    private bool _busy;
    private bool _allowClose;

    internal RasterEngineWindow(RasterLayer layer)
    {
        _layer = layer;
        InitializeComponent();
        DataContext = this;
        Title = $"Analyse raster : {layer.Name}";
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
    public string SelectedPalette
    {
        get => _selectedPalette;
        set
        {
            if (string.Equals(_selectedPalette, value, StringComparison.Ordinal)) return;
            _selectedPalette = value;
            OnPropertyChanged();
            RecolorClasses();
        }
    }
    public string SelectedClassificationMethod { get => _selectedClassificationMethod; set => Set(ref _selectedClassificationMethod, value); }
    public string SelectedBand { get => _selectedBand; set => Set(ref _selectedBand, value); }
    public string RedBand { get => _redBand; set => Set(ref _redBand, value); }
    public string GreenBand { get => _greenBand; set => Set(ref _greenBand, value); }
    public string BlueBand { get => _blueBand; set => Set(ref _blueBand, value); }
    public string ClassCount { get => _classCount; set => Set(ref _classCount, value); }
    public string Minimum { get => _minimum; set => Set(ref _minimum, value); }
    public string Maximum { get => _maximum; set => Set(ref _maximum, value); }
    public string OutlineWidth { get => _outlineWidth; set => Set(ref _outlineWidth, value); }
    public bool MaskNoDataAutomatically { get => _maskNoDataAutomatically; set => Set(ref _maskNoDataAutomatically, value); }
    public bool AddBlackOutline { get => _addBlackOutline; set => Set(ref _addBlackOutline, value); }
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
                total_pixel_count = sample.TotalPixelCount,
                sampled_pixel_count = sample.SampledPixelCount,
                sample_count = sample.SampleCount,
                nodata_sample_count = sample.NoDataSampleCount,
                observed_unique_count = sample.ObservedUniqueCount,
                profile_limited = sample.ProfileLimited,
                minimum = sample.Minimum,
                maximum = sample.Maximum,
                mean = sample.Mean,
                median = sample.Median,
                categorical = sample.IsCategorical,
                raster_type = sample.RasterType,
                theme = sample.Theme,
                confidence = sample.ThemeConfidence,
                rationale = sample.ThemeRationale,
                nomenclature = new
                {
                    key = sample.Nomenclature.Key,
                    name = sample.Nomenclature.Name,
                    confidence = sample.Nomenclature.Confidence,
                    rationale = sample.Nomenclature.Rationale,
                    classes = sample.Nomenclature.Classes,
                },
                quantile_breaks = sample.QuantileBreaks,
                continuous_classes = sample.ContinuousClasses,
                frequencies = sample.Frequencies.Select(item => new { value = item.Key, count = item.Value }).ToArray(),
                automatic_nodata_values = sample.AutomaticNoDataValues,
                has_raster_attribute_table = sample.HasRasterAttributeTable,
                nodata_candidates = sample.NoDataCandidates,
                anomalous_values = sample.AnomalousValues,
                possible_missing_codes = sample.PossibleMissingCodes,
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
        _lastSample = sample;
        SummaryText = $"Type : {RasterTypeLabel(sample.RasterType)}\nBandes : {sample.BandCount}\nDimensions : {sample.Width:N0} × {sample.Height:N0}\n" +
            $"Pixels échantillonnés : {sample.SampledPixelCount:N0}\nPixels valides : {sample.SampleCount:N0}\n" +
            $"Valeurs distinctes : {sample.ObservedUniqueCount:N0}{(sample.ProfileLimited ? " ou plus" : string.Empty)}\n" +
            $"Minimum valide : {sample.Minimum:G15}\nMaximum valide : {sample.Maximum:G15}\nMoyenne : {sample.Mean:G15}\nMédiane : {sample.Median:G15}\n" +
            $"Nomenclature : {sample.Nomenclature.Name} ({sample.Nomenclature.Confidence:P0})\n" +
            $"NoData masqué automatiquement : {FormatValues(sample.AutomaticNoDataValues)}";
        ThemeEvidenceText = $"{ThemeLabel(sample.Theme)}, confiance {sample.ThemeConfidence:P0}\n" +
            $"Schéma proposé : {sample.Nomenclature.Name}, confiance {sample.Nomenclature.Confidence:P0}\n" +
            string.Join("\n", sample.ThemeRationale.Concat(sample.Nomenclature.Rationale).Distinct());
        MetadataText = JsonSerializer.Serialize(new
        {
            sample.BandCount,
            sample.Width,
            sample.Height,
            sample.TotalPixelCount,
            sample.NoData,
            sample.SampledPixelCount,
            sample.SampleCount,
            sample.NoDataSampleCount,
            sample.ObservedUniqueCount,
            sample.ProfileLimited,
            sample.Minimum,
            sample.Maximum,
            sample.Mean,
            sample.Median,
            sample.RasterType,
            sample.Theme,
            sample.ThemeConfidence,
            sample.Nomenclature,
            sample.ContinuousClasses,
            sample.AutomaticNoDataValues,
            sample.HasRasterAttributeTable,
            sample.AnomalousValues,
            sample.PossibleMissingCodes,
        }, new JsonSerializerOptions { WriteIndented = true });
        _selectedNoDataValues.Clear();
        _declaredNoDataValues.Clear();
        foreach (var value in sample.AutomaticNoDataValues)
            _selectedNoDataValues.Add(value);
        NoDataCandidates.Clear();
        foreach (var candidate in sample.NoDataCandidates)
        {
            var declared = candidate.Reason.Contains("déclarée", StringComparison.OrdinalIgnoreCase);
            var automatic = sample.AutomaticNoDataValues.Any(value => SameNumber(value, candidate.Value));
            if (declared) _declaredNoDataValues.Add(candidate.Value);
            NoDataCandidates.Add(new NoDataCandidateRow(
                candidate.Value.ToString("G15", CultureInfo.InvariantCulture),
                candidate.Confidence.ToString("P0", CultureInfo.CurrentCulture),
                candidate.Reason,
                declared ? "NoData fournisseur" : automatic ? "Masquage automatique" : "À vérifier",
                declared));
        }
        Bands.Clear();
        for (var index = 1; index <= Math.Max(1, sample.BandCount); index++) Bands.Add($"{index} · Bande {index}");
        SelectedBand = Bands.First();
        RedBand = Bands.ElementAtOrDefault(0) ?? SelectedBand;
        GreenBand = Bands.ElementAtOrDefault(1) ?? SelectedBand;
        BlueBand = Bands.ElementAtOrDefault(2) ?? SelectedBand;
        Minimum = sample.Minimum.ToString("G15", CultureInfo.InvariantCulture);
        Maximum = sample.Maximum.ToString("G15", CultureInfo.InvariantCulture);
        SelectedRenderMode = sample.RasterType == "rgb" ? "Composition RGB" : sample.IsCategorical ? "Catégoriel" : "Continu";
        SelectedThemeProfile = ThemeLabel(sample.Theme);
        SelectedPalette = sample.RasterType == "rgb"
            ? "Continuous"
            : sample.IsCategorical && !string.IsNullOrWhiteSpace(sample.Nomenclature.Palette)
                ? sample.Nomenclature.Palette
                : PaletteLabel(sample.Theme, sample.RasterType);
        Classes.Clear();
        if (sample.IsCategorical)
        {
            var total = Math.Max(1, sample.Frequencies.Values.Sum());
            var proposals = sample.Nomenclature.Classes.Count > 0
                ? sample.Nomenclature.Classes
                : sample.Frequencies.OrderBy(item => item.Key)
                    .Select((item, index) => new NativeRasterClassProposal(
                        item.Key,
                        $"Classe {item.Key:G15}",
                        NativeStyleService.ResolvePalette(SelectedPalette, sample.Frequencies.Count)[index],
                        0.60,
                        "Code détecté"))
                    .ToArray();
            foreach (var proposal in proposals.Take(128))
            {
                var count = sample.Frequencies.FirstOrDefault(item => SameNumber(item.Key, proposal.Value)).Value;
                Classes.Add(new RasterClassRow
                {
                    Visible = true,
                    ValuesText = proposal.Value.ToString("G15", CultureInfo.InvariantCulture),
                    Label = proposal.Label,
                    Color = proposal.Color,
                    OpacityPercent = 100,
                    PixelCount = count,
                    Percentage = 100d * count / total,
                    BorderPercentage = sample.BorderPercentages.GetValueOrDefault(proposal.Value),
                    Status = $"{proposal.Source}, confiance {proposal.Confidence:P0}",
                    ShowInLegend = true,
                });
            }
            var allTotal = Math.Max(1, sample.AllFrequencies.Values.Sum());
            foreach (var value in sample.AutomaticNoDataValues)
            {
                var entry = sample.AllFrequencies.FirstOrDefault(item => SameNumber(item.Key, value));
                if (entry.Value <= 0 || Classes.Any(item => item.Values().Any(current => SameNumber(current, value)))) continue;
                Classes.Add(new RasterClassRow
                {
                    Visible = false,
                    ValuesText = value.ToString("G15", CultureInfo.InvariantCulture),
                    Label = "NoData détecté",
                    Color = "#FFFFFF",
                    OpacityPercent = 0,
                    PixelCount = entry.Value,
                    Percentage = 100d * entry.Value / allTotal,
                    BorderPercentage = sample.BorderPercentages.GetValueOrDefault(entry.Key),
                    Status = "NoData automatique",
                    ShowInLegend = false,
                });
            }
        }
        else
        {
            foreach (var range in sample.ContinuousClasses)
            {
                Classes.Add(new RasterClassRow
                {
                    Visible = true,
                    ValuesText = $"{range.LowerBound.ToString("G15", CultureInfo.InvariantCulture)}; {range.UpperBound.ToString("G15", CultureInfo.InvariantCulture)}",
                    Label = range.Label,
                    Color = range.Color,
                    OpacityPercent = 100,
                    Status = $"{range.Source}, confiance {range.Confidence:P0}",
                    ShowInLegend = true,
                });
            }
        }
        _automaticClasses.Clear();
        _automaticClasses.AddRange(Classes.Select(item => item.Clone()));
        ClassCount = Math.Clamp(Classes.Count(item => item.Visible), 2, 64).ToString(CultureInfo.InvariantCulture);
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
            .Select(item => $"{CartomizeDataService.Text(item, "name")} : {CartomizeDataService.Text(item, "formula")} ({CartomizeDataService.Number(item, "confidence"):P0})");
        SummaryText = string.Join(Environment.NewLine, new[]
        {
            $"Type : {rasterType}", $"Thème : {theme}", $"Confiance : {confidence:P0}",
            $"Symbologie recommandée : {CartomizeDataService.Text(inference, "recommended_renderer")}",
            "", "Diagnostic", string.Join(Environment.NewLine, rationale.Select(item => $"• {item}")),
            "", "Rôles de bandes détectés", string.Join(Environment.NewLine, semantics.Select(item => $"• {item}")),
            "", "Indices spectraux calculables", string.Join(Environment.NewLine, indices.Select(item => $"• {item}")),
        });
        ThemeEvidenceText = $"Type recommandé : {ThemeLabel(theme)}, confiance : {confidence:P0}" +
            (rationale.Any() ? Environment.NewLine + string.Join(" ", rationale.TakeLast(3)) : string.Empty);

        NoDataCandidates.Clear();
        foreach (var item in ReadObjects(inference, "nodata_candidates"))
            NoDataCandidates.Add(new NoDataCandidateRow(
                CartomizeDataService.Number(item, "value").ToString("G15", CultureInfo.InvariantCulture),
                CartomizeDataService.Number(item, "confidence").ToString("P0", CultureInfo.CurrentCulture),
                CartomizeDataService.Text(item, "reason"),
                "À vérifier",
                false));

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
            var previousOutline = false;
            if (preview && _previewDefinition is null)
                _previewDefinition = await QueuedTask.Run(() => _layer.GetDefinition());
            if (!preview)
            {
                if (_previewDefinition is not null)
                    await RestoreDefinitionAsync(_previewDefinition);
                _previewDefinition = null;
                _history.Push(await QueuedTask.Run(() => _layer.GetDefinition()));
                previousOutline = await NativeRasterOutlineService.ExistsAsync(_layer);
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
                        SelectedPalette,
                        Classes.Where(item => item.Values().Any())
                            .Select(item => new NativeRasterClassStyle(
                                item.Values().LastOrDefault(),
                                item.ShowInLegend ? item.Label : string.Empty,
                                item.Color,
                                item.Visible,
                                item.OpacityPercent))
                            .ToArray(),
                        MaskNoDataAutomatically,
                        _selectedNoDataValues.ToArray()));
            var outlineApplied = false;
            if (!preview)
            {
                _outlineHistory.Push(previousOutline);
                outlineApplied = await NativeRasterOutlineService.ApplyAsync(
                    _layer,
                    AddBlackOutline,
                    ParseDouble(OutlineWidth, 1.2));
            }
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
                automatic_nodata_mask = MaskNoDataAutomatically,
                visual_nodata_values = _selectedNoDataValues.OrderBy(value => value).ToArray(),
                black_raster_outline = AddBlackOutline,
                outline_width_points = ParseDouble(OutlineWidth, 1.2),
                outline_applied = outlineApplied,
                expert_confirmed = ExpertConfirmed,
                classes = Classes.Select(item => item.ToPayload()).ToArray(),
                preview,
                non_destructive = true,
            });
            StatusText = preview
                ? "Aperçu actif. Le NoData est transparent et les pixels source restent inchangés."
                : AddBlackOutline && !outlineApplied
                    ? "Symbologie appliquée. Le contour est indisponible hors d’une carte 2D active."
                    : AddBlackOutline
                        ? "Symbologie appliquée. Le NoData est masqué et le contour noir est actualisé."
                        : "Symbologie appliquée. Le NoData est masqué et aucun contour d’emprise n’est ajouté.";
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
        if (_outlineHistory.Count > 0)
            await NativeRasterOutlineService.ApplyAsync(
                _layer,
                _outlineHistory.Pop(),
                ParseDouble(OutlineWidth, 1.2));
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
                if (MaskNoDataAutomatically)
                    rgb.NoDataColor = CIMColor.CreateRGBColor(255, 255, 255, 0);
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
        _selectedNoDataValues.Clear();
        if (_lastSample is not null)
            foreach (var value in _lastSample.AutomaticNoDataValues)
                _selectedNoDataValues.Add(value);
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
        foreach (var candidate in NoDataGrid.SelectedItems.OfType<NoDataCandidateRow>().ToArray())
        {
            if (!double.TryParse(candidate.Value, NumberStyles.Float, CultureInfo.InvariantCulture, out var value)) continue;
            if (keep && candidate.IsDeclared)
            {
                StatusText = "Le NoData déclaré par le fournisseur reste masqué; seule une reclassification explicite peut le convertir en donnée.";
                continue;
            }
            if (keep) _selectedNoDataValues.RemoveWhere(item => SameNumber(item, value));
            else _selectedNoDataValues.Add(value);
            var row = Classes.FirstOrDefault(item => item.Values().Any(current => Math.Abs(current - value) < 1e-12));
            if (row is null && _lastSample is not null)
            {
                var frequency = _lastSample.AllFrequencies.FirstOrDefault(item => SameNumber(item.Key, value));
                if (frequency.Value > 0)
                {
                    row = new RasterClassRow
                    {
                        ValuesText = value.ToString("G15", CultureInfo.InvariantCulture),
                        Label = $"Classe {value:G15}",
                        Color = NativeStyleService.ResolvePalette(SelectedPalette, Math.Max(2, Classes.Count + 1))[Classes.Count],
                        PixelCount = frequency.Value,
                        BorderPercentage = _lastSample.BorderPercentages.GetValueOrDefault(frequency.Key),
                        Visible = keep,
                        ShowInLegend = keep,
                        OpacityPercent = keep ? 100 : 0,
                    };
                    Classes.Add(row);
                }
            }
            if (row is null) continue;
            row.Visible = keep;
            row.ShowInLegend = keep;
            row.OpacityPercent = keep ? Math.Max(1, row.OpacityPercent) : 0;
            if (keep && row.Color.Equals("#FFFFFF", StringComparison.OrdinalIgnoreCase))
                row.Color = NativeStyleService.ResolvePalette(SelectedPalette, Math.Max(2, Classes.Count))[Math.Max(0, Classes.IndexOf(row))];
            row.Status = keep ? "conservée" : "NoData visuel";
            var index = NoDataCandidates.IndexOf(candidate);
            if (index >= 0)
                NoDataCandidates[index] = candidate with { State = keep ? "Conservée comme classe" : "Masquage demandé" };
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
        var dialog = new SaveFileDialog { Filter = "Fichier de couche ArcGIS Pro (*.lyrx)|*.lyrx", FileName = $"Cartomize-{SafeName(_layer.Name)}.lyrx" };
        if (dialog.ShowDialog() != true) return;
        try
        {
            await QueuedTask.Run(() =>
            {
                var document = new LayerDocument(_layer);
                document.Save(dialog.FileName);
            });
            StatusText = $"Style ArcGIS Pro enregistré : {dialog.FileName}";
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write("Raster Engine — enregistrement LYRX", exception);
            StatusText = exception.Message;
        }
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

    private static string RasterTypeLabel(string key) => (key ?? string.Empty).Trim().ToLowerInvariant() switch
    {
        "binary" => "Carte binaire",
        "categorized" => "Raster catégoriel",
        "rgb" => "Image multibande RGB",
        "continuous" => "Surface continue",
        _ => key,
    };

    private static string FormatValues(IEnumerable<double> values)
    {
        var formatted = values.Select(value => value.ToString("G15", CultureInfo.InvariantCulture)).ToArray();
        return formatted.Length == 0 ? "aucune valeur supplémentaire" : string.Join(", ", formatted);
    }

    private static bool SameNumber(double left, double right)
        => Math.Abs(left - right) <= Math.Max(1e-12, Math.Abs(right) * 1e-12);

    private static string PaletteLabel(string theme, string rasterType)
    {
        var key = string.IsNullOrWhiteSpace(theme)
            ? (rasterType is "binary" or "categorized" ? "categorical" : "continuous")
            : theme;
        return string.Join(" ", key.Split('_').Select(word => CultureInfo.InvariantCulture.TextInfo.ToTitleCase(word)));
    }

    private void RecolorClasses()
    {
        if (Classes.Count == 0) return;
        var colors = NativeStyleService.ResolvePalette(SelectedPalette, Classes.Count);
        for (var index = 0; index < Classes.Count; index++)
            Classes[index].Color = colors[index % colors.Count];
        ClassGrid?.Items.Refresh();
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

public sealed record NoDataCandidateRow(
    string Value,
    string Confidence,
    string Reason,
    string State,
    bool IsDeclared);

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
