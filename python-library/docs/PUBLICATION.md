# Publier Cartomize Python

Le dossier est préparé pour créer un paquet PyPI. Aucune publication ni
réservation de nom n'a été effectuée. Le nom de distribution `cartomize`
est un nom de travail; sa disponibilité sera confirmée lors de la publication.

## Vérifier et construire

Depuis `python-library` :

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m build
python -m twine check dist/*
```

Les fichiers attendus sont `cartomize-0.7.0a1-py3-none-any.whl` et
`cartomize-0.7.0a1.tar.gz`. Tester l'installation du wheel dans un environnement
neuf avant diffusion. Tester aussi sur Windows, qui est la plateforme de
nombreux utilisateurs SIG.

## TestPyPI

Créer un compte sur https://test.pypi.org/, vérifier l'adresse électronique
et configurer la double authentification. Utiliser un jeton via l'invite
sécurisée de Twine ou un éditeur de confiance; ne pas placer de jeton dans
le code, les scripts, Git ou la documentation.

```bash
python -m twine upload --repository testpypi dist/*
```

Pour éviter de chercher les dépendances sur TestPyPI, les installer depuis
PyPI dans un environnement de test, puis installer le paquet TestPyPI sans
résolution de dépendances :

```bash
python -m pip install geopandas matplotlib numpy pyproj rasterio
python -m pip install --index-url https://test.pypi.org/simple/ --no-deps cartomize==0.7.0a1
```

## Publication publique

Après validation, créer/configurer le compte https://pypi.org/ de l'auteur et
publier les mêmes fichiers :

```bash
python -m twine upload dist/*
```

Le suffixe `a3` signale une alpha. Pour cette version, communiquer la commande
explicite `python -m pip install cartomize==0.7.0a1`. Les versions alpha ne sont
généralement pas sélectionnées par défaut quand des versions stables existent.
Chaque nouvelle livraison doit avoir un nouveau numéro de version.

Ajouter sur la page publique une description bilingue, les exemples,
captures de cartes et le guide utilisateur. Relayer cette page sur le site
Cartomize et dans la communauté. La publication sur PyPI distribue le logiciel;
elle ne constitue pas une certification de sa qualité.

Références officielles :

- https://packaging.python.org/en/latest/tutorials/packaging-projects/
- https://pypi.org/help/
