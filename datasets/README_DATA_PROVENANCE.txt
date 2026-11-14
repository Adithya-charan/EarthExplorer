EARTH TREND EXPLORER — DATA PACKAGE

IMPORTANT PROVENANCE NOTICE
This package contains two different data classes. Do not mix or misrepresent them.

1) datasets/observed_global/
   NASA GPM IMERG V07 global area-averaged precipitation and random-error CSVs.
   These are observed source data, but they are global area averages, not regional extracts.
   They cannot support India/Amazon/Central Africa regional claims or regional maps.

2) datasets/synthetic_regional_demo/
   India, Amazon, and Central Africa regional-shaped demo series created for software testing.
   These are synthetic, illustrative values and are NOT NASA regional observations.
   Their provenance labels and filenames intentionally identify them as synthetic/demo.
   Do not remove or conceal those labels. Do not publish their trends as scientific findings.

3) datasets/supporting/
   Additional project demo/inventory CSVs. Inspect each file's columns and provenance before use.

The NASA precipitation variable is a rate in mm/hr. Preserve the unit. Do not silently
convert it to monthly accumulated precipitation. Random error is an uncertainty-related
variable, not automatically a confidence interval.
