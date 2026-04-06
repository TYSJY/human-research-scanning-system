# Release process

## Local checks

```bash
python -m pip install -e .
pytest -q
python -m compileall research_os tests
python scripts/sync_bundled_resources.py --check
```

## Version bump

- update `pyproject.toml`
- update `research_os/__init__.py`
- update `research_os/ux.py`
- update `research_os/workspace.py`
- update sample project state versions if needed
- prepend a new entry to `CHANGELOG.md`

## GitHub Release

```bash
git tag v0.6.6
git push origin v0.6.6
```

The release workflow builds source and wheel distributions and uploads them to the GitHub Release page.
