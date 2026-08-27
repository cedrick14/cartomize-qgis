using ArcGIS.Desktop.Framework.Contracts;
using Cartomize.ArcGISPro.Services;
using Cartomize.ArcGISPro.Views;

namespace Cartomize.ArcGISPro.Commands;

internal sealed class OpenDockPaneButton : Button
{
    protected override void OnClick() => CartomizeDockPaneViewModel.Show();
}

internal abstract class ToolButton : Button
{
    protected abstract string ToolName { get; }
    protected override void OnClick() => GeoprocessingService.Open(ToolName);
}

internal sealed class AuditButton : ToolButton { protected override string ToolName => "AuditProject"; }
internal sealed class AutopilotButton : ToolButton { protected override string ToolName => "AutopilotMap"; }
internal sealed class VectorButton : ToolButton { protected override string ToolName => "VectorIntelligence"; }
internal sealed class RasterButton : ToolButton { protected override string ToolName => "RasterIntelligence"; }
internal sealed class GeoButton : ToolButton { protected override string ToolName => "GeoIntelligence"; }
internal sealed class LayoutButton : ToolButton { protected override string ToolName => "CreateLayout"; }
internal sealed class BatchButton : ToolButton { protected override string ToolName => "BatchMaps"; }
internal sealed class ReplayButton : ToolButton { protected override string ToolName => "ReplayRecipe"; }
