# Installer Cartomize dans ArcGIS Pro

Le paquet prêt à installer se trouve ici :

```text
release\Cartomize-ArcGISPro-10.5.1.esriAddInX
```

1. Fermez ArcGIS Pro.
2. Ouvrez le dossier `release`.
3. Double-cliquez sur `Cartomize-ArcGISPro-10.5.1.esriAddInX`.
4. Cliquez sur **Install Add-In**.
5. Relancez ArcGIS Pro et ouvrez un projet cartographique.
6. Vérifiez la présence de l'onglet **Cartomize** dans le ruban.

Si Windows bloque le fichier, cliquez droit sur le `.esriAddInX`, choisissez
**Propriétés**, cochez **Débloquer**, puis recommencez l'installation.

L'installation gérée par Esri est normalement enregistrée sous :

```text
%USERPROFILE%\Documents\ArcGIS\AddIns\ArcGISPro
```

Après une nouvelle compilation dans Visual Studio, le paquet brut est généré
dans :

```text
src\Cartomize.ArcGISPro\bin\Release\net10.0-windows\Cartomize.ArcGISPro.esriAddInX
```

Le script `scripts\build-addin.ps1` le copie automatiquement dans `release`.
