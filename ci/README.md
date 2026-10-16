CI workflows. Copy them into `.github/workflows/` to enable them on GitHub
(they are kept here because the publishing token has no `workflow` scope).

- `validate.yml` – hassfest + HACS validation.
- `release.yml` – creates the GitHub Release `X.Y.Z` (needed by HACS) automatically
  when `manifest.json` changes the version on `main`.
