# IDC question library

64 questions people ask about the Imaging Data Commons, with the answer from the current data release and the SQL behind it.

**To use one:** copy its SQL into the **🧪 SQL playground** of IDC Explorer (or the notebook), run it, and change the values to fit your question.

- [Patients, studies and scans](#patients-studies-and-scans)
- [Imaging types](#imaging-types)
- [Body parts](#body-parts)
- [Download size](#download-size)
- [Licences](#licences)
- [Patients' sex](#patients-sex)
- [Scanners](#scanners)
- [Open in the viewer](#open-in-the-viewer)
- [Datasets](#datasets)
- [Analysis results](#analysis-results)
- [IDC releases](#idc-releases)
- [File types](#file-types)
- [Common mistakes](#common-mistakes)

## Patients, studies and scans

### How many patients are in the rider_pilot collection?

**patients** = 8

```sql
SELECT COUNT(DISTINCT PatientID) AS patients
FROM index
WHERE collection_id = 'rider_pilot'
```

### How many studies and series are in rider_pilot?

**studies** = 154, **series** = 774

```sql
SELECT COUNT(DISTINCT StudyInstanceUID) AS studies,
       COUNT(*) AS series
FROM index
WHERE collection_id = 'rider_pilot'
```

### What is the total download size of rider_pilot in MB?

**total_size_MB** = 11259.2

```sql
SELECT ROUND(SUM(series_size_MB), 1) AS total_size_MB
FROM index
WHERE collection_id = 'rider_pilot'
```

### How many distinct patients, studies, and series are in the current index?

**patients** = 86362, **studies** = 168507, **series** = 1044191

```sql
SELECT COUNT(DISTINCT PatientID) AS patients,
       COUNT(DISTINCT StudyInstanceUID) AS studies,
       COUNT(*) AS series
FROM index
```

### How many patients in rider_pilot have at least one CT series?

**patients** = 8

```sql
SELECT COUNT(DISTINCT PatientID) AS patients
FROM index
WHERE collection_id = 'rider_pilot' AND Modality = 'CT'
```

### How many series in rider_pilot have a source DOI?

**series** = 774

```sql
SELECT COUNT(*) AS series
FROM index
WHERE collection_id = 'rider_pilot' AND source_DOI IS NOT NULL
```


## Imaging types

### How many CT series are in rider_pilot?

**series** = 172

```sql
SELECT COUNT(*) AS series
FROM index
WHERE collection_id = 'rider_pilot' AND Modality = 'CT'
```

### Which modalities are present in rider_pilot?

| Modality | series |
|---|---|
| PR | 240 |
| SEG | 200 |
| CT | 172 |

```sql
SELECT Modality, COUNT(*) AS series
FROM index
WHERE collection_id = 'rider_pilot'
GROUP BY Modality
ORDER BY series DESC, Modality
```

### How many MR series are in the whole index?

**series** = 128143

```sql
SELECT COUNT(*) AS series
FROM index
WHERE Modality = 'MR' AND analysis_result_id IS NULL
```

### How many PET (PT) series are original data?

**series** = 5929

```sql
SELECT COUNT(*) AS series
FROM index
WHERE Modality = 'PT' AND analysis_result_id IS NULL
```

### How many slide microscopy series are in IDC?

**series** = 76300

```sql
SELECT COUNT(*) AS series
FROM index
WHERE Modality = 'SM' AND analysis_result_id IS NULL
```

### How many segmentation series are in IDC?

**series** = 193295

```sql
SELECT COUNT(*) AS series
FROM index
WHERE Modality = 'SEG'
```

### How many CR series are original data?

**series** = 12534

```sql
SELECT COUNT(*) AS series
FROM index
WHERE Modality = 'CR' AND analysis_result_id IS NULL
```

### How many DX series are original data?

**series** = 3712

```sql
SELECT COUNT(*) AS series
FROM index
WHERE Modality = 'DX' AND analysis_result_id IS NULL
```

### How many RTSTRUCT series are in the index?

**series** = 19366

```sql
SELECT COUNT(*) AS series
FROM index
WHERE Modality = 'RTSTRUCT'
```

### How many distinct modalities are in the index?

**modalities** = 25

```sql
SELECT COUNT(DISTINCT Modality) AS modalities
FROM index
```

### How many original series have Modality NULL?

**series** = 0

```sql
SELECT COUNT(*) AS series
FROM index
WHERE Modality IS NULL
```


## Body parts

### How many original chest CT series are in IDC?

**series** = 205851, **patients** = 29340

```sql
SELECT COUNT(*) AS series, COUNT(DISTINCT PatientID) AS patients
FROM index
WHERE Modality = 'CT'
  AND BodyPartExamined = 'CHEST'
  AND analysis_result_id IS NULL
```

### How many original head CT series are there?

**series** = 228

```sql
SELECT COUNT(*) AS series
FROM index
WHERE Modality = 'CT'
  AND BodyPartExamined = 'HEAD'
  AND analysis_result_id IS NULL
```

### How many original brain MR series are there?

**series** = 266

```sql
SELECT COUNT(*) AS series
FROM index
WHERE Modality = 'MR'
  AND BodyPartExamined = 'BRAIN'
  AND analysis_result_id IS NULL
```

### How many original breast MR series are there?

**series** = 48333

```sql
SELECT COUNT(*) AS series
FROM index
WHERE Modality = 'MR'
  AND BodyPartExamined = 'BREAST'
  AND analysis_result_id IS NULL
```

### How many original abdomen CT series are there?

**series** = 9797

```sql
SELECT COUNT(*) AS series
FROM index
WHERE Modality = 'CT'
  AND BodyPartExamined = 'ABDOMEN'
  AND analysis_result_id IS NULL
```

### How many original pelvis CT series are there?

**series** = 462

```sql
SELECT COUNT(*) AS series
FROM index
WHERE Modality = 'CT'
  AND BodyPartExamined = 'PELVIS'
  AND analysis_result_id IS NULL
```

### Which body parts appear on original CT, and how often?

| BodyPartExamined | series |
|---|---|
| CHEST | 205851 |
| None | 31571 |
| ABDOMEN | 9797 |

```sql
SELECT BodyPartExamined, COUNT(*) AS series
FROM index
WHERE Modality = 'CT' AND analysis_result_id IS NULL
GROUP BY BodyPartExamined
ORDER BY series DESC, BodyPartExamined
LIMIT 15
```

### How many original chest CR or DX series are there?

**series** = 15519

```sql
SELECT COUNT(*) AS series
FROM index
WHERE Modality IN ('CR', 'DX')
  AND BodyPartExamined = 'CHEST'
  AND analysis_result_id IS NULL
```


## Download size

### Give me the three smallest non-empty CT series in rider_pilot.

| SeriesInstanceUID | series_size_MB |
|---|---|
| 1.3.6.1.4.1.9328.50.1.53734 | 0.53 |
| 1.3.6.1.4.1.9328.50.1.54657 | 0.53 |
| 1.3.6.1.4.1.9328.50.1.69736 | 0.53 |

```sql
SELECT SeriesInstanceUID, ROUND(series_size_MB, 2) AS series_size_MB
FROM index
WHERE collection_id = 'rider_pilot'
  AND Modality = 'CT'
  AND series_size_MB > 0
ORDER BY series_size_MB ASC, SeriesInstanceUID
LIMIT 3
```

### What is the size of the smallest non-empty series in rider_pilot?

**min_mb** = 0.0

```sql
SELECT ROUND(MIN(series_size_MB), 2) AS min_mb
FROM index
WHERE collection_id = 'rider_pilot' AND series_size_MB > 0
```

### How many original series are larger than 1 GB?

**series** = 11749

```sql
SELECT COUNT(*) AS series
FROM index
WHERE analysis_result_id IS NULL AND series_size_MB >= 1024
```

### How many original CT series are under 1 MB?

**series** = 21819

```sql
SELECT COUNT(*) AS series
FROM index
WHERE Modality = 'CT'
  AND analysis_result_id IS NULL
  AND series_size_MB > 0
  AND series_size_MB < 1
```

### Do the three smallest rider_pilot CT series have an S3 url?

**with_url** = 3

```sql
SELECT COUNT(*) AS with_url
FROM (
  SELECT series_aws_url
  FROM index
  WHERE collection_id = 'rider_pilot'
    AND Modality = 'CT'
    AND series_size_MB > 0
  ORDER BY series_size_MB ASC, SeriesInstanceUID
  LIMIT 3
)
WHERE series_aws_url IS NOT NULL
```

### What is the median series size in MB for original chest CT? Use a quantile.

**median_mb** = 66.3

```sql
SELECT ROUND(quantile_cont(series_size_MB, 0.5), 1) AS median_mb
FROM index
WHERE Modality = 'CT'
  AND BodyPartExamined = 'CHEST'
  AND analysis_result_id IS NULL
  AND series_size_MB > 0
```

### Sum of series_size_MB for the three smallest rider_pilot CT series.

**total_size_MB** = 1.58

```sql
SELECT ROUND(SUM(series_size_MB), 2) AS total_size_MB
FROM (
  SELECT series_size_MB
  FROM index
  WHERE collection_id = 'rider_pilot'
    AND Modality = 'CT'
    AND series_size_MB > 0
  ORDER BY series_size_MB ASC, SeriesInstanceUID
  LIMIT 3
)
```


## Licences

### Which licences apply to rider_pilot, and how many series use each?

**license_short_name** = CC BY 4.0, **series** = 774

```sql
SELECT license_short_name, COUNT(*) AS series
FROM index
WHERE collection_id = 'rider_pilot'
GROUP BY license_short_name
ORDER BY series DESC, license_short_name
```

### How many distinct licence names are in the index?

**licences** = 5

```sql
SELECT COUNT(DISTINCT license_short_name) AS licences
FROM index
```

### Which licence covers the most series?

| license_short_name | series |
|---|---|
| CC BY 4.0 | 877215 |
| CC BY 3.0 | 132303 |
| CC BY-NC 4.0 | 28783 |

```sql
SELECT license_short_name, COUNT(*) AS series
FROM index
GROUP BY license_short_name
ORDER BY series DESC, license_short_name
LIMIT 5
```


## Patients' sex

### How many female patients are in rider_pilot?

**patients** = 2

```sql
SELECT COUNT(DISTINCT PatientID) AS patients
FROM index
WHERE collection_id = 'rider_pilot' AND PatientSex = 'F'
```

### How many male patients are in rider_pilot?

**patients** = 3

```sql
SELECT COUNT(DISTINCT PatientID) AS patients
FROM index
WHERE collection_id = 'rider_pilot' AND PatientSex = 'M'
```

### What patient sexes are recorded in rider_pilot?

| PatientSex | patients |
|---|---|
| M | 3 |
| None | 3 |
| F | 2 |

```sql
SELECT PatientSex, COUNT(DISTINCT PatientID) AS patients
FROM index
WHERE collection_id = 'rider_pilot'
GROUP BY PatientSex
ORDER BY patients DESC, PatientSex
```

### How many original series have PatientSex = 'F'?

**series** = 178801

```sql
SELECT COUNT(*) AS series
FROM index
WHERE PatientSex = 'F' AND analysis_result_id IS NULL
```

### How many original series have PatientSex = 'M'?

**series** = 104153

```sql
SELECT COUNT(*) AS series
FROM index
WHERE PatientSex = 'M' AND analysis_result_id IS NULL
```


## Scanners

### Which manufacturers produced rider_pilot series?

| Manufacturer | series |
|---|---|
| Siemens Corporate Research | 500 |
| GE MEDICAL SYSTEMS | 192 |
| CoreLab Partners, Inc. | 40 |

```sql
SELECT Manufacturer, COUNT(*) AS series
FROM index
WHERE collection_id = 'rider_pilot'
GROUP BY Manufacturer
ORDER BY series DESC, Manufacturer
```

### How many distinct manufacturers are in the original CT index?

**manufacturers** = 45

```sql
SELECT COUNT(DISTINCT Manufacturer) AS manufacturers
FROM index
WHERE Modality = 'CT' AND analysis_result_id IS NULL
```


## Open in the viewer

### Give me five chest CT studies I can open in the viewer.

| collection_id | StudyInstanceUID | SeriesInstanceUID | Modality |
|---|---|---|---|
| cptac_lscc | 1.3.6.1.4.1.14519.5.2.1.2932.1975.254952 | 1.3.6.1.4.1.14519.5.2.1.2932.1975.176380 | CT |
| tcga_luad | 1.3.6.1.4.1.14519.5.2.1.7777.9002.142043 | 1.3.6.1.4.1.14519.5.2.1.7777.9002.849099 | CT |
| tcga_luad | 1.3.6.1.4.1.14519.5.2.1.7777.9002.142043 | 1.3.6.1.4.1.14519.5.2.1.7777.9002.130923 | CT |

```sql
SELECT collection_id, StudyInstanceUID, SeriesInstanceUID, Modality
FROM index
WHERE Modality = 'CT'
  AND BodyPartExamined = 'CHEST'
  AND analysis_result_id IS NULL
  AND series_size_MB > 0
ORDER BY series_size_MB ASC, SeriesInstanceUID
LIMIT 5
```

### Give me the StudyInstanceUID values for the three smallest rider_pilot CT series.

| StudyInstanceUID | SeriesInstanceUID |
|---|---|
| 1.3.6.1.4.1.9328.50.1.54652 | 1.3.6.1.4.1.9328.50.1.54657 |
| 1.3.6.1.4.1.9328.50.1.53671 | 1.3.6.1.4.1.9328.50.1.53734 |
| 1.3.6.1.4.1.9328.50.1.69732 | 1.3.6.1.4.1.9328.50.1.69736 |

```sql
SELECT StudyInstanceUID, SeriesInstanceUID
FROM index
WHERE collection_id = 'rider_pilot'
  AND Modality = 'CT'
  AND series_size_MB > 0
ORDER BY series_size_MB ASC, SeriesInstanceUID
LIMIT 3
```

### List one series per rider_pilot patient, the smallest CT if they have one.

| PatientID | SeriesInstanceUID | series_size_MB |
|---|---|---|
| 1.3.6.1.4.1.9328.50.1.0109 | 1.3.6.1.4.1.9328.50.1.54657 | 0.53 |
| 1.3.6.1.4.1.9328.50.1.0117 | 1.3.6.1.4.1.9328.50.1.57707 | 2.28 |
| 1.3.6.1.4.1.9328.50.1.0121 | 1.3.6.1.4.1.9328.50.1.69736 | 0.53 |

```sql
SELECT PatientID, SeriesInstanceUID, ROUND(series_size_MB, 2) AS series_size_MB
FROM (
  SELECT PatientID, SeriesInstanceUID, series_size_MB,
         ROW_NUMBER() OVER (PARTITION BY PatientID ORDER BY series_size_MB, SeriesInstanceUID) AS rn
  FROM index
  WHERE collection_id = 'rider_pilot'
    AND Modality = 'CT'
    AND series_size_MB > 0
)
WHERE rn = 1
ORDER BY PatientID
```


## Datasets

### How many collections are described in collections_index?

**collections** = 179

```sql
SELECT COUNT(*) AS collections
FROM collections_index
```

### Which collections mention lung in the cancer type or tumor location?

| collection_id | subjects |
|---|---|
| nlst | 26410 |
| eay131 | 2813 |
| covid_19_ny_sbu | 1384 |

```sql
SELECT collection_id, subjects
FROM collections_index
WHERE lower(coalesce(cancer_types, '')) LIKE '%lung%'
   OR lower(coalesce(tumor_locations, '')) LIKE '%lung%'
ORDER BY subjects DESC, collection_id
LIMIT 20
```

### Which collections mention breast cancer?

| collection_id | subjects |
|---|---|
| cbis_ddsm | 6671 |
| breast_cancer_screening_dbt | 5060 |
| victre | 2994 |

```sql
SELECT collection_id, subjects
FROM collections_index
WHERE lower(coalesce(cancer_types, '')) LIKE '%breast%'
ORDER BY subjects DESC, collection_id
LIMIT 20
```

### How many collections are marked Completed?

**collections** = 0

```sql
SELECT COUNT(*) AS collections
FROM collections_index
WHERE status = 'Completed'
```

### How many collections are marked Ongoing?

**collections** = 37

```sql
SELECT COUNT(*) AS collections
FROM collections_index
WHERE status = 'Ongoing'
```

### What species values are listed on collections?

| species | collections |
|---|---|
| Human | 163 |
| Mouse | 10 |
| Phantom | 3 |

```sql
SELECT species, COUNT(*) AS collections
FROM collections_index
GROUP BY species
ORDER BY collections DESC, species
LIMIT 10
```

### Which 10 collections have the most subjects?

| collection_id | subjects |
|---|---|
| nlst | 26410 |
| cbis_ddsm | 6671 |
| breast_cancer_screening_dbt | 5060 |

```sql
SELECT collection_id, subjects
FROM collections_index
ORDER BY subjects DESC, collection_id
LIMIT 10
```

### Is rider_pilot present in collections_index, and how many subjects does that row report?

**collection_id** = rider_pilot, **subjects** = 8, **status** = Complete

```sql
SELECT collection_id, subjects, status
FROM collections_index
WHERE collection_id = 'rider_pilot'
```


## Analysis results

### How many analysis-result collections are listed?

**collections** = 26

```sql
SELECT COUNT(*) AS collections
FROM analysis_results_index
```

### How many series in the index point at an analysis result?

**series** = 474083

```sql
SELECT COUNT(*) AS series
FROM index
WHERE analysis_result_id IS NOT NULL
```


## IDC releases

### What is the newest series_revised_idc_version in the index?

**latest_version** = 25

```sql
SELECT MAX(series_revised_idc_version) AS latest_version
FROM index
```

### How many series first appeared in IDC version 1?

**series** = 38153

```sql
SELECT COUNT(*) AS series
FROM index
WHERE series_init_idc_version = 1
```


## File types

### What SOP class names appear in rider_pilot?

| sop_class_name | series |
|---|---|
| Grayscale Softcopy Presentation State St | 240 |
| Segmentation Storage | 200 |
| CT Image Storage | 172 |

```sql
SELECT sop_class_name, COUNT(*) AS series
FROM index
WHERE collection_id = 'rider_pilot'
GROUP BY sop_class_name
ORDER BY series DESC, sop_class_name
```

### How many series use a transfer syntax whose name contains JPEG?

**series** = 99839

```sql
SELECT COUNT(*) AS series
FROM index
WHERE transfer_syntax_name ILIKE '%JPEG%'
```


## Common mistakes

### Does the uppercase collection id RIDER_PILOT match any series?

**series** = 0

```sql
SELECT COUNT(*) AS series
FROM index
WHERE collection_id = 'RIDER_PILOT'
```

### How many rider_pilot series are original data rather than analysis results?

**series** = 194

```sql
SELECT COUNT(*) AS series
FROM index
WHERE collection_id = 'rider_pilot' AND analysis_result_id IS NULL
```

### How many rider_pilot series are analysis results?

**series** = 580

```sql
SELECT COUNT(*) AS series
FROM index
WHERE collection_id = 'rider_pilot' AND analysis_result_id IS NOT NULL
```

### For SM series, how often is BodyPartExamined null?

**series** = 76300, **with_body_part** = 0

```sql
SELECT
  COUNT(*) AS series,
  COUNT(BodyPartExamined) AS with_body_part
FROM index
WHERE Modality = 'SM'
```

### Is PatientAge stored as a number or do we have to read the DICOM age string?

**age_type** = VARCHAR, **filled** = 231153

```sql
SELECT typeof(PatientAge) AS age_type, COUNT(PatientAge) AS filled
FROM index
WHERE PatientAge IS NOT NULL
GROUP BY 1
```
