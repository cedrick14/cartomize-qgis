# Contributing to Cartomize

Thank you for contributing to Cartomize.

## Development principles

- Keep the plugin compatible with the declared QGIS version range.
- Prefer native PyQGIS/QGIS APIs over reimplementing GIS rendering logic.
- Do not modify user source datasets during analysis or styling.
- Keep long-running tasks cancelable and avoid GUI access from worker threads.
- Add or update tests for bug fixes and new algorithms.
- Write new code comments and public developer documentation in English.
- Do not commit credentials, tokens, private keys, user datasets or private project files.

## Before opening a pull request

Run:

```bash
python tools/preflight.py
```

If security tools are installed, also run:

```bash
bandit -r cartomize_qgis/
detect-secrets scan cartomize_qgis/
flake8 cartomize_qgis/
```

## Issues

Use GitHub Issues for reproducible bugs and feature requests. Include QGIS version, operating system, plugin version, traceback and a minimal reproducible dataset when possible.
