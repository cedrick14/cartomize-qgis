using System;
using System.IO;
using System.Windows;
using System.Windows.Controls;

namespace Cartomize.ArcGISPro.Views;

public partial class CartomizeDockPaneView : UserControl
{
    public CartomizeDockPaneView()
    {
        try
        {
            InitializeComponent();
        }
        catch (Exception exception)
        {
            WriteLoadError(exception);
            Content = new Border
            {
                Padding = new Thickness(16),
                Child = new TextBlock
                {
                    Text = "Impossible de charger l’interface Cartomize. Consultez le journal Cartomize.",
                    TextWrapping = TextWrapping.Wrap,
                },
            };
        }
    }

    private static void WriteLoadError(Exception exception)
    {
        try
        {
            var directory = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Cartomize",
                "Logs");
            Directory.CreateDirectory(directory);
            File.AppendAllText(
                Path.Combine(directory, "ui-load.log"),
                $"{DateTimeOffset.Now:O}{Environment.NewLine}{exception}{Environment.NewLine}{Environment.NewLine}");
        }
        catch
        {
            // Une erreur de journalisation ne doit jamais arrêter ArcGIS Pro.
        }
    }
}
