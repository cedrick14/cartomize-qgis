# QGIS plugin repository submission

Cartomize is prepared for submission to the official QGIS Python Plugin Repository with the following public metadata:

- Homepage: https://github.com/cedrick14/cartomize-qgis
- Source repository: https://github.com/cedrick14/cartomize-qgis
- Issue tracker: https://github.com/cedrick14/cartomize-qgis/issues
- Maintainer: ONDON NKOUA Cédrick Belmich
- Maintainer email: belmich300@gmail.com
- QGIS compatibility: 3.40 to 3.99
- Experimental: True

Before uploading a release:

1. Push the exact source corresponding to the ZIP to the public repository.
2. Confirm GitHub Issues is enabled and the three URLs above are publicly reachable.
3. Run the repository quality workflow and resolve any blocking Bandit or detect-secrets findings.
4. Run `python tools/preflight.py`.
5. Build the official plugin archive with `python tools/build_plugin_zip.py`.
6. Install the generated ZIP in a clean QGIS profile and run the smoke tests.
7. Upload the generated archive to the official QGIS plugin repository using an OSGeo ID.

Do not submit a ZIP whose source differs from the public repository at the corresponding release/tag.
