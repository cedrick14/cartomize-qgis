using System.IO;
using System.Reflection;
using ArcGIS.Desktop.Framework;
using Cartomize.ArcGISPro.Services;

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

    public static string TemplatesDirectory => Path.Combine(InstallationDirectory, "Templates");

    public static string UserDataDirectory
    {
        get
        {
            var root = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            var directory = Path.Combine(root, "ESRI", "Cartomize", "10.5.1");
            Directory.CreateDirectory(directory);
            return directory;
        }
    }

    protected override bool Initialize()
    {
        StartupGuard.EnsureInitialized("Initialisation du module Cartomize");
        try
        {
            return base.Initialize();
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write("Initialisation du module ArcGIS Pro", exception);
            return false;
        }
    }

    protected override bool CanUnload() => true;
}
