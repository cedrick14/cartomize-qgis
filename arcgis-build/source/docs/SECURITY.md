# Sécurité et protection des données

## Principes

- aucune géométrie, valeur raster, table attributaire ou emprise n'est téléversée ;
- aucune clé, mot de passe ou jeton n'est requis ;
- le catalogue de 24 maquettes est local ;
- les JSON sont bornés en taille et validés avant usage ;
- aucun script n'est accepté dans une maquette ;
- les recettes sont validées par leur schéma ;
- les sorties utilisent des chemins explicitement choisis par l'utilisateur ;
- la symbologie n'écrit pas dans les sources de données.

## Surface de confiance

La boîte `.pyt` s'exécute dans l'environnement Python d'ArcGIS Pro et l'add-in .NET dans le processus ArcGIS Pro. N'installez que des paquets provenant de Cartomize ou d'un canal vérifié. Signez le `.esriAddInX` avant diffusion externe.

## Dépendances

Le projet source ne redistribue aucune DLL Esri. Les références de compilation sont restaurées depuis le paquet officiel `Esri.ArcGISPro.Extensions30`. Aucune dépendance Python tierce n'est ajoutée à `arcgispro-py3`.

## Signalement

Signaler les problèmes de sécurité à `support@cartomizeplugin.com` sans joindre de données confidentielles ni de clés privées.
