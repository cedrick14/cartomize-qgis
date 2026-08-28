namespace Cartomize.ArcGISPro.Views;

internal sealed record ChoiceItem(string Id, string Label)
{
    public override string ToString() => Label;
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
