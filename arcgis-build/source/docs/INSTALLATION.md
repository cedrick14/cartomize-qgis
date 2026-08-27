# Installation et compilation

## Option A — Utiliser immédiatement la boîte à outils

Cette option ne nécessite ni Visual Studio ni compilation.

1. Décompressez le paquet Cartomize.
2. Conservez ensemble :
   - `Cartomize.pyt` ;
   - `cartomize_core/` ;
   - `templates_library/`.
3. Ouvrez un projet ArcGIS Pro 3.7.
4. Dans le volet **Catalogue**, cliquez droit sur **Boîtes à outils**.
5. Choisissez **Ajouter une boîte à outils**.
6. Sélectionnez `Cartomize.pyt`.
7. Commencez par **Auditer le projet**, puis **Autopilote Cartomize**.

## Option B — Compiler l'interface complète

### Prérequis

- Windows 11 64 bits ;
- ArcGIS Pro 3.7 ;
- Visual Studio 2026 18.4.1 ou plus récent ;
- charge de travail Développement Desktop .NET ;
- .NET 10 ;
- extension Visual Studio **ArcGIS Pro SDK for .NET 3.7**.

### Compilation

Ouvrez PowerShell dans le dossier racine :

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\build-addin.ps1
```

Ou ouvrez `Cartomize.ArcGISPro.sln` dans Visual Studio et compilez en `Release`.

Le projet utilise le paquet NuGet officiel `Esri.ArcGISPro.Extensions30` version `3.7.0.1901`. La sortie attendue est :

```text
release\Cartomize-ArcGISPro-10.5.1.esriAddInX
```

Dans Visual Studio, une compilation directe place d'abord le paquet sous :

```text
src\Cartomize.ArcGISPro\bin\Release\net10.0-windows\Cartomize.ArcGISPro.esriAddInX
```

Le script `build-addin.ps1` le copie ensuite dans le dossier `release` avec le nom de diffusion indiqué ci-dessus.

> Important : `Config.daml` doit rester un élément `Content` sans
> `CopyToOutputDirectory="PreserveNewest"`. Sinon le SDK Esri le place sous
> `Install\`, ne le trouve plus à la racine et ne génère aucun `.esriAddInX`.

### Installation du `.esriAddInX`

1. Fermez ArcGIS Pro.
2. Double-cliquez sur `Cartomize-ArcGISPro-10.5.1.esriAddInX`.
3. Vérifiez l'auteur et cliquez **Install Add-In**.
4. Relancez ArcGIS Pro.
5. Ouvrez l'onglet **Cartomize**.

Le gestionnaire Esri installe normalement l'add-in dans `Documents\ArcGIS\AddIns\ArcGISPro`.

## Signature pour une diffusion publique

Avant publication, signez le `.esriAddInX` avec `ArcGISSignAddIn.exe` et un certificat de signature de code approuvé :

```powershell
& "C:\Program Files\ArcGIS\Pro\bin\ArcGISSignAddIn.exe" `
  ".\release\Cartomize-ArcGISPro-10.5.1.esriAddInX" `
  /n:"NOM DU TITULAIRE DU CERTIFICAT"
```

Ne placez jamais un certificat privé, un mot de passe ou une clé dans le dépôt.
