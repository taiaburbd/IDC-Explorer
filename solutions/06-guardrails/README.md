# Guardrails

`guardrails.py` looks at the series a person is about to download.

- If the total `series_size_MB` is at least 1024 MB, the result carries a warning and the manifest is withheld until `confirm_large` is set.
- Every distinct `license_short_name` is listed with the result, with a reminder to read the licence and the collection DOI.

The hosted assistant calls `assess_download` on the full cohort and `allow_manifest` before it returns an s5cmd manifest.

```bash
../../.venv/bin/python -c "
from guardrails import assess
print(assess([{'series_size_MB': 2000, 'license_short_name': 'CC BY 4.0'}]))
"
```
