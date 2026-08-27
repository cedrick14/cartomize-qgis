using System.Diagnostics;
using System.Windows.Input;
using ArcGIS.Desktop.Framework;
using ArcGIS.Desktop.Framework.Contracts;
using Cartomize.ArcGISPro.Services;

namespace Cartomize.ArcGISPro.Views;

internal sealed class CartomizeDockPaneViewModel : DockPane
{
    private const string DockPaneId = "Cartomize_ArcGISPro_DockPane";

    protected CartomizeDockPaneViewModel()
    {
        AuditCommand = Command("AuditProject");
        AutopilotCommand = Command("AutopilotMap");
        VectorCommand = Command("VectorIntelligence");
        RasterCommand = Command("RasterIntelligence");
        GeoCommand = Command("GeoIntelligence");
        LayoutCommand = Command("CreateLayout");
        BatchCommand = Command("BatchMaps");
        ReplayCommand = Command("ReplayRecipe");
        MapOpsCommand = Command("MapOpsCheck");
        CommunityCommand = new DelegateCommand(OpenCommunityPortal);
    }

    public string VersionText => "Cartomize 10.5.1-arcgispro.3 · ArcGIS Pro 3.7";
    public ICommand AuditCommand { get; }
    public ICommand AutopilotCommand { get; }
    public ICommand VectorCommand { get; }
    public ICommand RasterCommand { get; }
    public ICommand GeoCommand { get; }
    public ICommand LayoutCommand { get; }
    public ICommand BatchCommand { get; }
    public ICommand ReplayCommand { get; }
    public ICommand MapOpsCommand { get; }
    public ICommand CommunityCommand { get; }

    public static void Show()
    {
        var pane = FrameworkApplication.DockPaneManager.Find(DockPaneId);
        pane?.Activate();
    }

    private static ICommand Command(string name) =>
        new DelegateCommand(() => GeoprocessingService.Open(name));

    private static void OpenCommunityPortal()
    {
        Process.Start(new ProcessStartInfo
        {
            FileName = "https://cartomizeplugin.com/",
            UseShellExecute = true,
        });
    }
}
