# Publication de Cartomize sur PyPI

Paquet : `cartomize` · Version préparée : `0.8.1a1` · Auteur : ONDON NKOUA Cédrick Belmich.

Le paquet est une version alpha. La préparation des fichiers et du workflow ne signifie pas qu’un téléversement a réussi. La page publique et les empreintes des fichiers doivent être vérifiées après publication. Une réponse 404 de l’API publique n’est pas une réservation du nom ; seul PyPI peut accepter définitivement le premier dépôt.

## Compte PyPI

Utiliser le compte PyPI du fondateur, avec une adresse vérifiée et la double authentification. La connexion et l’authentification à deux facteurs s’effectuent sur PyPI ou dans le formulaire sécurisé de connexion, jamais en communiquant les secrets dans une conversation.

Pour une première publication par GitHub, ouvrir **Publishing** dans les paramètres du compte PyPI et ajouter un **pending trusted publisher** avec les valeurs suivantes :

| Champ PyPI | Valeur |
|---|---|
| PyPI Project Name | `cartomize` |
| Owner | `cedrick14` |
| Repository name | `cartomize-qgis` |
| Workflow name | `pypi-publish.yml` |
| Environment name | `pypi` |

Cette configuration autorise ce workflow du dépôt à publier Cartomize. Elle ne réserve pas le nom. Au premier téléversement réussi, le compte qui a configuré le publisher devient propriétaire du projet PyPI. Pour TestPyPI, la configuration est distincte et l’environnement est `testpypi`.

## Workflow GitHub

Le fichier `.github/workflows/pypi-publish.yml` construit uniquement le wheel et la distribution source de la version courante. Il exécute les tests, Twine en mode strict et `scripts/check_release.py`, puis conserve les deux fichiers comme artefact GitHub. L’autorisation OIDC est limitée au travail de publication. Aucun jeton permanent n’est stocké dans le code.

Un push ordinaire sur `feat/cartomize-python-library` valide les distributions **sans publication**. Après configuration du publisher, un commit de lancement explicite contenant `[publish pypi]` dans son message sur cette branche déclenche le dépôt de la version courante après validation. Cette voie permet le premier dépôt avec l’accès GitHub déjà établi, sans fusion de la branche principale.

Un tag `python-vVERSION` déclenche également la publication sur PyPI après validation ; son numéro doit correspondre au `pyproject.toml`. Pour cette version, le tag est `python-v0.8.1a1`. Le tag doit pointer vers le commit contenant le workflow et les fichiers validés, après configuration du publisher PyPI. Utiliser une seule des méthodes pour une même version.

Le workflow prévoit aussi une exécution manuelle avec `check`, `testpypi` ou `pypi`. Le bouton **Run workflow** dans GitHub nécessite la présence du workflow sur la branche par défaut. La méthode par tag n’impose pas de fusionner le code dans la branche principale avant le premier dépôt.

Le dépôt contient aussi les extensions QGIS et ArcGIS Pro : les tags de publication Python utilisent donc obligatoirement le préfixe `python-v`.

## Construction locale

Depuis `python-library`, choisir un répertoire vide réservé à la publication :

```bash
python -m pip install build twine
python -m build --outdir pypi-dist
python -m twine check --strict pypi-dist/*
python scripts/check_release.py pypi-dist
```

Les deux fichiers attendus sont :

- `cartomize-0.8.1a1-py3-none-any.whl`
- `cartomize-0.8.1a1.tar.gz`

Ne pas utiliser un ancien répertoire `dist` contenant plusieurs versions pour le téléversement. La description publique vient de `README_PYPI.md`, avec des liens absolus et une présentation française/anglaise.

## Alternative manuelle avec Twine

Si la publication de confiance n’est pas utilisée, configurer un jeton PyPI dans le compte, puis lancer :

```bash
python -m twine upload --username __token__ pypi-dist/cartomize-0.8.1a1-py3-none-any.whl pypi-dist/cartomize-0.8.1a1.tar.gz
```

Twine demande le jeton dans son invite masquée. Ne pas l’inscrire dans la ligne de commande, le dépôt ou une conversation. Pour un premier projet, le jeton de création peut nécessiter une portée de compte ; après création du projet, privilégier une publication de confiance ou un jeton limité au projet.

## Après publication

Vérifier la version, les fichiers et leurs SHA256 sur PyPI, puis installer depuis l’index public dans un environnement distinct :

```bash
python -m pip install "cartomize[gui]==0.8.1a1"
python -m cartomize gui
```

Le suffixe `a1` signale une alpha. Chaque nouvelle livraison publique reçoit un numéro différent ; les fichiers déjà publiés ne sont pas remplaçables sous le même nom. La présence sur PyPI est une distribution publique, pas une certification scientifique.

Références officielles :

- https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/
- https://docs.pypi.org/trusted-publishers/using-a-publisher/
- https://packaging.python.org/en/latest/tutorials/packaging-projects/
