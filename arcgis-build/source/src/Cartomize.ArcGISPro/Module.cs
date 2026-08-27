using System.IO;
using System.Reflection;
using ArcGIS.Desktop.Framework;

namespace Cartomize.ArcGISPro;

internal sealed class Module : ArcGIS.Desktop.Framework.Contracts.Module
{
    private static Module? _this;

    public static Module Current => _this ??=
        (Module)FrameworkApplication.FindModule("Cartomize_ArcGISPro_Module");

    public static string InstallationDirectory
    {
        get
        {
            var assemblyPath = Assembly.GetExecutingAssembly().Location;
            return Path.GetDirectoryName(assemblyPath)
                   ?? throw new InvalidOperationException("Le dossier de l’extension Cartomize est introuvable.");
        }
    }

    public static string ToolboxPath => Path.Combine(InstallationDirectory, "Toolbox", "Cartomize.pyt");

    protected override bool CanUnload() => true;
}
