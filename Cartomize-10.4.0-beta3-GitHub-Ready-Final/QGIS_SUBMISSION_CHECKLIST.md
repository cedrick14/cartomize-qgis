# Cartomize QGIS Official Submission Checklist

## Repository and identity

- [ ] Public source repository created and accessible without login
- [ ] Public issue tracker enabled
- [ ] Maintainer email is real and monitored
- [ ] `python tools/configure_submission.py ...` completed
- [ ] `metadata.txt` contains no placeholder values
- [ ] Repository contents match the plugin sources packaged for QGIS

## Metadata

- [x] Plugin name: Cartomize
- [x] Short description in English
- [x] Detailed About text in English
- [x] Author name: ONDON NKOUA Cédrick Belmich
- [x] QGIS minimum: 3.40
- [x] QGIS maximum: 3.99
- [x] Experimental: True
- [x] Processing provider declared
- [x] Proper icon included
- [ ] Working homepage URL
- [ ] Working public repository URL
- [ ] Working issue tracker URL

## Package

- [x] `metadata.txt` present
- [x] `__init__.py` present with `classFactory`
- [x] `LICENSE` present
- [x] README documentation present
- [x] Plugin package below 25 MB
- [x] No DLL/EXE/SO/PYD binaries
- [x] No `.env`, private key, SQLite database, `__pycache__` or `.pyc`
- [x] Single top-level plugin directory in generated ZIP
- [x] 24 JSON templates are valid

## Security

- [x] Local structural scan rejects `eval`, `exec`, `shell=True`, `os.system` and obvious embedded credentials
- [ ] GitHub Bandit scan green
- [ ] GitHub detect-secrets scan green
- [ ] GitHub Flake8 report reviewed
- [ ] Official plugins.qgis.org scan status = Validated

## Runtime validation

- [x] Target QGIS 3.40.x is explicitly declared
- [x] QGIS 4 support is not advertised
- [ ] Final beta3 ZIP tested in QGIS 3.40 on Windows
- [ ] Final beta3 ZIP tested in QGIS 3.x on Linux
- [ ] macOS test completed if a test machine is available
- [ ] Plugin loads without traceback
- [ ] Processing provider loads
- [ ] Autopilot creates a native QGIS layout
- [ ] Raster Intelligence opens and analyses sample raster
- [ ] Vector Intelligence analyses sample vector layer
- [ ] PDF/PNG export verified

## Official QGIS upload

- [ ] OSGeo ID created
- [ ] Log in to plugins.qgis.org
- [ ] Upload `Cartomize-10.4.0-beta3-QGIS-OFFICIAL-SUBMISSION.zip`
- [ ] Wait for security status `Validated`
- [ ] Review Security tab findings
- [ ] Wait for staff approval of the new plugin
