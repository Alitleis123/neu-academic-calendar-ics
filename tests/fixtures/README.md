# Source fixtures

These two public Northeastern registrar PDFs were retrieved on September 14,
2026. `sources.json` records their source URLs and SHA-256 fingerprints.
They are test inputs, not authoritative calendars for subscribers.

The fixtures cover both supported layouts, seven pages for 2025-2026 and three
for 2026-2027. Tests verify full descriptions, date ranges, classifications and
the complete build without requiring the registrar website to be available.

Replace a fixture only after reviewing its source changes and updating the
expected counts and fingerprints. Keep regression coverage for the timezone
text `ET`, which the original PDF reader mistook for an operator.
