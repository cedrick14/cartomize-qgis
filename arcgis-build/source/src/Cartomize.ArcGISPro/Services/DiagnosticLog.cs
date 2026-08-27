using System.IO;
using System.Text;

namespace Cartomize.ArcGISPro.Services;

internal static class DiagnosticLog
{
    private static readonly object SyncRoot = new();

    public static string DirectoryPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "ESRI",
        "Cartomize",
        "10.5.1",
        "Logs");

    public static string FilePath => Path.Combine(DirectoryPath, "cartomize.log");

    public static void Write(string operation, Exception exception)
    {
        try
        {
            Directory.CreateDirectory(DirectoryPath);
            var entry = new StringBuilder()
                .AppendLine($"[{DateTimeOffset.Now:O}] {operation}")
                .AppendLine(exception.ToString())
                .AppendLine()
                .ToString();
            lock (SyncRoot)
                File.AppendAllText(FilePath, entry, Encoding.UTF8);
        }
        catch
        {
            // La journalisation ne doit jamais interrompre ArcGIS Pro.
        }
    }
}
