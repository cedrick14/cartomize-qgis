# Release Process

1. Update version in plugin metadata, constants and bundled template metadata.
2. Configure the real public repository and maintainer email.
3. Run `python tools/preflight.py`.
4. Push to the public repository and wait for the `plugin-quality` GitHub workflow.
5. Test the exact commit in QGIS 3.40 on Windows and at least one Unix-like platform.
6. Run `python tools/build_plugin_zip.py`.
7. Confirm the ZIP contains only the `cartomize_qgis/` root directory.
8. Upload the generated ZIP to the official QGIS plugin repository using an OSGeo ID.
9. Wait for the official security scan. Bandit and detect-secrets findings marked critical must be resolved by uploading a new version.
10. Once the new plugin is approved, tag the exact public repository commit used for the submitted ZIP.
