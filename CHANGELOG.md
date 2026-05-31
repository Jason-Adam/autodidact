# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Versioning

A release is cut by bumping the version in **both** `pyproject.toml` and
`src/__init__.py` to the same value, then tagging and pushing:

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

The `release.yml` workflow runs the test suite, fails fast if the tag does not
match both version sources, builds `autodidact-vX.Y.Z.tar.gz`, and publishes a
GitHub release with that tarball plus the standalone `install.sh`.

## [Unreleased]

### Added

- Release-based installation: a `curl ... | bash` one-liner that downloads a
  GitHub release tarball and installs autodidact without a checkout
  (`install.sh` with `--version`, `--update`, and `--uninstall`). Downloads are
  SHA-256 verified against the release's `sha256sums.txt` and validated against
  path traversal before extraction.
- `install.py --release` mode: installs from a copied source tree at
  `~/.claude/autodidact/` instead of symlinking a development checkout.
- `release.yml` workflow: tag-triggered build that gates on tests, guards
  against version drift across `pyproject.toml`, `src/__init__.py`, and the git
  tag, and publishes the tarball and `install.sh` as release assets.

## [0.1.0]

Initial development version.
