using System.Windows.Input;
using ArcGIS.Desktop.Framework.Dialogs;
using Cartomize.ArcGISPro.Services;

namespace Cartomize.ArcGISPro.Views;

internal sealed class DelegateCommand(Action execute) : ICommand
{
    private readonly Func<bool>? _canExecute;

    public DelegateCommand(Action execute, Func<bool>? canExecute) : this(execute)
    {
        _canExecute = canExecute;
    }

    public event EventHandler? CanExecuteChanged;
    public bool CanExecute(object? parameter) => _canExecute?.Invoke() ?? true;
    public void Execute(object? parameter)
    {
        try
        {
            execute();
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write("Commande Cartomize", exception);
            MessageBox.Show(
                $"La commande n’a pas pu être exécutée.\n\nJournal : {DiagnosticLog.FilePath}\n\nErreur : {exception.Message}",
                "Cartomize 10.5.1");
        }
    }
    public void RaiseCanExecuteChanged() => CanExecuteChanged?.Invoke(this, EventArgs.Empty);
}

internal sealed class AsyncDelegateCommand : ICommand
{
    private readonly Func<Task> _execute;
    private readonly Func<bool>? _canExecute;
    private bool _running;

    public AsyncDelegateCommand(Func<Task> execute, Func<bool>? canExecute = null)
    {
        _execute = execute;
        _canExecute = canExecute;
    }

    public event EventHandler? CanExecuteChanged;

    public bool CanExecute(object? parameter) => !_running && (_canExecute?.Invoke() ?? true);

    public async void Execute(object? parameter)
    {
        if (!CanExecute(parameter))
            return;
        _running = true;
        RaiseCanExecuteChanged();
        try
        {
            await _execute();
        }
        catch (Exception exception)
        {
            DiagnosticLog.Write("Commande asynchrone Cartomize", exception);
            MessageBox.Show(
                $"La commande n’a pas pu être exécutée.\n\nJournal : {DiagnosticLog.FilePath}\n\nErreur : {exception.Message}",
                "Cartomize 10.5.1");
        }
        finally
        {
            _running = false;
            RaiseCanExecuteChanged();
        }
    }

    public void RaiseCanExecuteChanged() => CanExecuteChanged?.Invoke(this, EventArgs.Empty);
}
