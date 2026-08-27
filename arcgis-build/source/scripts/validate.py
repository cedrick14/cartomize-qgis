#!/usr/bin/env python3
"""Validation statique exécutable sans installation ArcGIS Pro."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    errors = []
    python_files = sorted((ROOT / "toolbox").rglob("*.py")) + sorted((ROOT / "toolbox").rglob("*.pyt"))
    for path in python_files:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except Exception as exc:
            errors.append(f"Python invalide {path.relative_to(ROOT)} : {exc}")

    xml_files = [ROOT / "src/Cartomize.ArcGISPro/Config.daml", ROOT / "src/Cartomize.ArcGISPro/Views/CartomizeDockPaneView.xaml"]
    for path in xml_files:
        try:
            ET.parse(path)
        except Exception as exc:
            errors.append(f"XML invalide {path.relative_to(ROOT)} : {exc}")

    csproj_path = ROOT / "src/Cartomize.ArcGISPro/Cartomize.ArcGISPro.csproj"
    csproj = csproj_path.read_text(encoding="utf-8")
    for required in ("net10.0-windows", "Esri.ArcGISPro.Extensions30", "3.7.0.1901"):
        if required not in csproj:
            errors.append(f"Configuration .NET absente : {required}")

    try:
        project = ET.parse(csproj_path).getroot()
        config_items = [
            item
            for item in project.findall(".//Content")
            if item.attrib.get("Include", "").replace("\\", "/") == "Config.daml"
        ]
        if not config_items:
            errors.append("Config.daml doit avoir l'action de génération Content.")
        elif config_items[0].attrib.get("CopyToOutputDirectory") not in (None, "", "Never"):
            errors.append(
                "Config.daml ne doit pas utiliser CopyToOutputDirectory=PreserveNewest : "
                "le SDK Esri ne créerait pas le .esriAddInX."
            )
    except Exception as exc:
        errors.append(f"Projet MSBuild invalide : {exc}")

    toolbox_text = (ROOT / "toolbox/Cartomize.pyt").read_text(encoding="utf-8")
    expected_tool_labels = (
        "Créer automatiquement une carte",
        "Rejouer une recette Cartomize",
        "Produire une série de cartes Cartomize",
        "Créer une mise en page Cartomize",
        "Contrôler la qualité cartographique du projet",
        "Vérifier les changements MapOps",
        "Analyser un raster avec Raster Engine",
        "Analyser le projet",
        "Analyser une couche vectorielle",
    )
    for label in expected_tool_labels:
        if label not in toolbox_text:
            errors.append(f"Libellé attendu absent de la boîte à outils ArcGIS : {label}")

    xaml_text = (ROOT / "src/Cartomize.ArcGISPro/Views/CartomizeDockPaneView.xaml").read_text(encoding="utf-8")
    visible_toolbox_labels = "\n".join(
        re.findall(r'self\.label\s*=\s*"([^"]*)"', toolbox_text)
    )
    if "intelligence" in (visible_toolbox_labels + xaml_text).casefold():
        errors.append("Le terme « intelligence » ne doit plus apparaître dans l’interface.")
    for tab in ("Automatisation", "Projet", "Mise en page", "Qualité", "Production", "Communauté", "Système"):
        if f'Header="{tab}"' not in xaml_text:
            errors.append(f"Onglet Cartomize QGIS absent du DockPane ArcGIS : {tab}")
    native_resources = (
        "Esri_DockPaneClientAreaBackgroundBrush",
        "Esri_BorderBrush",
        "Esri_ButtonBorderless",
        "Esri_TextBlockRegular",
        "Esri_TextBlockH1",
        "Esri_TextBlockH3",
        "Esri_TextBlockH7",
        "Esri_TextBlockDockPaneHeading",
    )
    for resource in native_resources:
        if resource not in xaml_text:
            errors.append(f"Ressource de thème ArcGIS Pro absente : {resource}")
    if re.search(r'BasedOn="\{DynamicResource\s+', xaml_text):
        errors.append(
            "Style.BasedOn doit utiliser StaticResource : DynamicResource provoque "
            "un échec de chargement du DockPane WPF."
        )
    for forbidden in ("Foreground=", "FontFamily=", "FontWeight=", "Color=\"#", "Background=\"#"):
        if forbidden in xaml_text:
            errors.append(
                "Le DockPane doit hériter du thème ArcGIS Pro sans style forcé : "
                f"{forbidden}"
            )

    view_model_text = (
        ROOT / "src/Cartomize.ArcGISPro/Views/CartomizeDockPaneViewModel.cs"
    ).read_text(encoding="utf-8")
    if 'VersionText => "Cartomize 10.5.1"' not in view_model_text:
        errors.append("La version visible doit être exactement Cartomize 10.5.1.")

    expected_icon_sha256 = "21b8d4f87575337215a0b7c5c4b82c42c612996f7f45188e5c8ec993184f3bf2"
    icon_path = ROOT / "src/Cartomize.ArcGISPro/Images/Cartomize.png"
    if hashlib.sha256(icon_path.read_bytes()).hexdigest() != expected_icon_sha256:
        errors.append("L’icône ArcGIS doit rester identique à l’icône QGIS 10.5.1.")

    qgis_raster_core_hashes = {
        "raster_intelligence_core.py": "ea267f2134e8abda04af7a53ae9a752fd0242ad7926b90eb778d15f09d99a869",
        "raster_sampling.py": "fed46fd7996d56e0e50b6e2a4a23545c95429f529d24ff24600d991590442e95",
        "band_semantics.py": "7b96a22980a377867b3357aebef2b1436def0dd43a8151c51ec72299d4b892d4",
    }
    for name, expected_hash in qgis_raster_core_hashes.items():
        path = ROOT / "toolbox/cartomize_core" / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            errors.append(
                f"Le noyau Raster Engine {name} doit rester identique à Cartomize QGIS 10.5.1."
            )

    qgis_pure_core_hashes = {
        "layer_stack.py": "03d503548f39f397928b848211548d1964cb2aa5c2958cdc91c4ea148bab5832",
        "raster_themes.py": "5b3891185b0bbda51c00a04d4516df4f30df9a6d7bdfe6590b561d551608e3da",
    }
    for name, expected_hash in qgis_pure_core_hashes.items():
        path = ROOT / "toolbox/cartomize_core" / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            errors.append(f"Le noyau commun {name} doit rester identique à Cartomize QGIS 10.5.1.")

    templates_root = ROOT / "templates_library"
    templates_digest = hashlib.sha256()
    for path in sorted(templates_root.rglob("*.json")):
        templates_digest.update(path.relative_to(templates_root).as_posix().encode())
        templates_digest.update(b"\0")
        templates_digest.update(path.read_bytes())
        templates_digest.update(b"\0")
    if templates_digest.hexdigest() != "17d584b0d70ef457f31b9d4fb0c3c45d057178e1ae66ea981e9adcd15e6580bc":
        errors.append("Les 24 maquettes et le catalogue doivent rester identiques au ZIP QGIS 10.5.1.")

    for required in (
        '"Manifeste de production JSON"',
        '"Utiliser uniquement les couches visibles"',
        '"Marge autour des données (%)"',
        '"Ajouter une grille"',
        '"Enregistrer la maquette ArcGIS Pro (PAGX)"',
        '("biodiversite", "Biodiversité")',
        '("scientifique", "Publication scientifique")',
    ):
        if required not in toolbox_text:
            errors.append(f"Contrat QGIS/ArcGIS absent de la boîte à outils : {required}")

    raster_adapter_text = (ROOT / "toolbox/cartomize_core/raster.py").read_text(encoding="utf-8")
    for required in (
        "resolve_raster_source(arcpy, source, source_text)",
        "raster = arcpy.Raster(raster_source)",
        '"non_destructive": True',
    ):
        if required not in raster_adapter_text:
            errors.append(f"Garantie Raster Engine absente : {required}")

    try:
        daml = ET.parse(ROOT / "src/Cartomize.ArcGISPro/Config.daml").getroot()
        namespace = {"esri": "http://schemas.esri.com/DADF/Registry"}
        ribbon_buttons = daml.findall(".//esri:controls/esri:button", namespace)
        captions = [item.attrib.get("caption") for item in ribbon_buttons]
        if captions != ["Ouvrir Cartomize"]:
            errors.append(
                "Le ruban doit conserver une seule action comme QGIS : Ouvrir Cartomize. "
                f"Valeurs trouvées : {captions}"
            )
        addin_info = daml.find("esri:AddInInfo", namespace)
        if addin_info is None or addin_info.attrib.get("version") != "10.5.1":
            errors.append("La version du manifeste Esri doit être exactement 10.5.1.")
    except Exception as exc:
        errors.append(f"Impossible de contrôler la parité du ruban : {exc}")

    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-p", "test_*.py", "-v"],
        cwd=ROOT,
        text=True,
    )
    if result.returncode:
        errors.append("Les tests unitaires ont échoué.")

    if errors:
        for error in errors:
            print("ERREUR", error)
        return 1
    print(f"VALIDÉ: {len(python_files)} sources Python, {len(xml_files)} sources XML et tous les tests unitaires.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
