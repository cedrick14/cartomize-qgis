namespace Cartomize.ArcGISPro.Views;

internal sealed class ProjectRasterClassItem
{
    public ProjectRasterClassItem(
        string value,
        string label,
        string color,
        double percentage,
        bool visible,
        string state)
    {
        Value = value;
        Label = label;
        Color = color;
        PercentageText = percentage > 0 ? $"{percentage:0.##} %" : "—";
        State = visible ? state : "Masqué · " + state;
    }

    public string Value { get; }
    public string Label { get; }
    public string Color { get; }
    public string PercentageText { get; }
    public string State { get; }

    public System.Windows.Media.Brush ColorBrush
    {
        get
        {
            try
            {
                var converted = System.Windows.Media.ColorConverter.ConvertFromString(Color);
                return converted is System.Windows.Media.Color value
                    ? new System.Windows.Media.SolidColorBrush(value)
                    : System.Windows.Media.Brushes.Gray;
            }
            catch
            {
                return System.Windows.Media.Brushes.Gray;
            }
        }
    }
}

internal sealed record ChoiceItem(string Id, string Label)
{
    public override string ToString() => Label;
}

internal sealed record LayerChoiceItem(
    string Id,
    string Name,
    bool IsRaster,
    bool IsBasemap)
{
    public override string ToString() => Name;
}

internal sealed record TemplateItem(
    string Id,
    string Name,
    string Category,
    string Description,
    string PageFormat,
    string Path)
{
    public string Label => $"{Category} — {Name}";
    public override string ToString() => Label;
}

internal sealed record AutomationProposal(
    string VariantId,
    string Name,
    string TemplateId,
    string TemplateName,
    string PageFormat,
    string Title,
    string Subtitle,
    double MarginPercent,
    bool AddGrid,
    string Decisions)
{
    public int Score { get; init; }
}

internal sealed record AuditFindingItem(
    string Severity,
    string Code,
    string Layer,
    string Message,
    string Remediation)
{
    public string Summary => string.IsNullOrWhiteSpace(Remediation) ? Message : $"{Message} — {Remediation}";
}

internal sealed record CommunityResourceItem(
    int Id,
    string Title,
    string Description,
    string Category,
    string PageFormat,
    string DetailUrl)
{
    public override string ToString() => Title;
}
