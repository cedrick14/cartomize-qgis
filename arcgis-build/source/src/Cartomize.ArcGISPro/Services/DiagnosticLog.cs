using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
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

    public static void Write(string operation)
    {
        WriteEntry($"[{DateTimeOffset.Now:O}] {operation}{Environment.NewLine}");
    }

    public static void Write(string operation, Exception exception)
    {
        WriteEntry(new StringBuilder()
            .AppendLine($"[{DateTimeOffset.Now:O}] {operation}")
            .AppendLine(exception.ToString())
            .ToString());
    }

    public static void WriteRuntimeSnapshot(string operation)
    {
        try
        {
            var assembly = Assembly.GetExecutingAssembly();
            var process = Environment.ProcessPath ?? "inconnu";
            WriteEntry(new StringBuilder()
                .AppendLine($"[{DateTimeOffset.Now:O}] {operation}")
                .AppendLine($"Processus : {process}")
                .AppendLine($"Architecture : {RuntimeInformation.ProcessArchitecture}")
                .AppendLine($"Runtime : {RuntimeInformation.FrameworkDescription}")
                .AppendLine($"Système : {RuntimeInformation.OSDescription}")
                .AppendLine($"Assembly : {assembly.FullName}")
                .AppendLine($"Emplacement : {assembly.Location}")
                .ToString());
        }
        catch
        {
            // La journalisation ne doit jamais interrompre ArcGIS Pro.
        }
    }

    private static void WriteEntry(string entry)
    {
        try
        {
            Directory.CreateDirectory(DirectoryPath);
            lock (SyncRoot)
                File.AppendAllText(FilePath, entry + Environment.NewLine, Encoding.UTF8);
        }
        catch
        {
            // La journalisation ne doit jamais interrompre ArcGIS Pro.
        }
    }
}
