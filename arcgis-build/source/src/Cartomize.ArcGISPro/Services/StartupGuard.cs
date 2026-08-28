using System.Reflection;
using System.Threading;
using System.Windows;
using System.Windows.Threading;

namespace Cartomize.ArcGISPro.Services;

internal static class StartupGuard
{
    private static int _initialized;

    public static void EnsureInitialized(string stage)
    {
        DiagnosticLog.Write($"Étape : {stage}");
        if (Interlocked.Exchange(ref _initialized, 1) != 0)
            return;

        DiagnosticLog.WriteRuntimeSnapshot("Initialisation du diagnostic de démarrage");

        try
        {
            var application = Application.Current;
            if (application is not null)
                application.DispatcherUnhandledException += OnDispatcherUnhandledException;
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write("Installation du gestionnaire WPF", exception);
        }

        AppDomain.CurrentDomain.UnhandledException += OnUnhandledException;
        TaskScheduler.UnobservedTaskException += OnUnobservedTaskException;
    }

    public static void Stage(string stage) => DiagnosticLog.Write($"Étape : {stage}");

    private static void OnDispatcherUnhandledException(
        object sender,
        DispatcherUnhandledExceptionEventArgs args)
    {
        if (!BelongsToCartomize(args.Exception))
            return;

        DiagnosticLog.Write("Exception WPF Cartomize interceptée", args.Exception);
        args.Handled = true;
    }

    private static void OnUnhandledException(object? sender, UnhandledExceptionEventArgs args)
    {
        if (args.ExceptionObject is Exception exception && BelongsToCartomize(exception))
            DiagnosticLog.Write("Exception fatale Cartomize", exception);
    }

    private static void OnUnobservedTaskException(object? sender, UnobservedTaskExceptionEventArgs args)
    {
        if (!BelongsToCartomize(args.Exception))
            return;

        DiagnosticLog.Write("Tâche Cartomize non observée", args.Exception);
        args.SetObserved();
    }

    private static bool BelongsToCartomize(Exception exception)
    {
        for (Exception? current = exception; current is not null; current = current.InnerException)
        {
            var declaringAssembly = current.TargetSite?.DeclaringType?.Assembly.GetName().Name;
            if (declaringAssembly?.StartsWith("Cartomize", StringComparison.OrdinalIgnoreCase) == true)
                return true;

            if (current.StackTrace?.Contains("Cartomize.ArcGISPro", StringComparison.Ordinal) == true)
                return true;

            if (current is ReflectionTypeLoadException loader &&
                loader.LoaderExceptions.Any(item => item is not null && BelongsToCartomize(item)))
                return true;
        }

        return false;
    }
}
