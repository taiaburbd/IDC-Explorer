"""
IDC Explorer – query engine.

All data logic lives here so it can be reused from the web app, a script,
or a future API. No user interface code in this file.

Data source: NCI Imaging Data Commons (IDC) through the `idc-index` package.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

import duckdb
import pandas as pd
from idc_index import IDCClient


# --------------------------------------------------------------------------
# Friendly names shown to non-technical users
# --------------------------------------------------------------------------

MODALITY_LABELS = {
    "CT": "CT scan",
    "MR": "MRI",
    "PT": "PET scan",
    "MG": "Mammography",
    "CR": "X-ray (CR)",
    "DX": "X-ray (digital)",
    "US": "Ultrasound",
    "SM": "Pathology slide (microscopy)",
    "NM": "Nuclear medicine",
    "XA": "Angiography",
    "SEG": "Segmentation (outlines of organs/tumours)",
    "RTSTRUCT": "Radiotherapy contours",
    "SR": "Structured report / measurements",
    "ANN": "Pathology annotations",
}

# Image types a normal user wants to look at (not derived objects)
IMAGE_MODALITIES = ["CT", "MR", "PT", "MG", "CR", "DX", "US", "SM", "NM", "XA"]

DIR_LAYOUTS = {
    "By collection → patient → scan type (recommended)": "%collection_id/%PatientID/%Modality_%SeriesInstanceUID",
    "By collection → patient → study → series": "%collection_id/%PatientID/%StudyInstanceUID/%Modality_%SeriesInstanceUID",
    "By scan type → patient": "%Modality/%PatientID/%SeriesInstanceUID",
    "Everything in one folder": "",
}

# Normalised MRI field strength in Tesla (some scanners store Gauss, e.g. 15000)
_FIELD_T = (
    "ROUND(CASE WHEN mr.MagneticFieldStrength > 100 "
    "THEN mr.MagneticFieldStrength / 10000 ELSE mr.MagneticFieldStrength END, 1)"
)
_AGE_YEARS = (
    "CASE WHEN i.PatientAge LIKE '%Y' "
    "THEN TRY_CAST(SUBSTR(i.PatientAge, 1, 3) AS INTEGER) END"
)


def q(value: str) -> str:
    """Safely quote a text value for SQL."""
    return "'" + str(value).replace("'", "''") + "'"


def q_list(values) -> str:
    return "(" + ", ".join(q(v) for v in values) + ")"


# --------------------------------------------------------------------------
# What the user selected ("recipe"). Saved/loaded as JSON for reproducibility.
# --------------------------------------------------------------------------

@dataclass
class Recipe:
    # General
    cancer_types: list[str] = field(default_factory=list)
    tumor_locations: list[str] = field(default_factory=list)
    collections: list[str] = field(default_factory=list)
    modalities: list[str] = field(default_factory=list)
    body_parts: list[str] = field(default_factory=list)
    manufacturers: list[str] = field(default_factory=list)
    sexes: list[str] = field(default_factory=list)
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    commercial_ok_only: bool = False
    with_segmentation_only: bool = False

    # CT settings
    ct_slice_min: Optional[float] = None
    ct_slice_max: Optional[float] = None
    ct_kvp: list[float] = field(default_factory=list)
    ct_kernels: list[str] = field(default_factory=list)

    # MRI settings
    mr_field_t: list[float] = field(default_factory=list)
    mr_acq_type: list[str] = field(default_factory=list)
    mr_slice_min: Optional[float] = None
    mr_slice_max: Optional[float] = None

    # PET settings
    pt_tracers: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Recipe":
        data = json.loads(text)
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def uses_ct(self) -> bool:
        return bool(self.ct_slice_min is not None or self.ct_slice_max is not None
                    or self.ct_kvp or self.ct_kernels)

    def uses_mr(self) -> bool:
        return bool(self.mr_field_t or self.mr_acq_type
                    or self.mr_slice_min is not None or self.mr_slice_max is not None)

    def uses_pt(self) -> bool:
        return bool(self.pt_tracers)

    def is_empty(self) -> bool:
        return self == Recipe()


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------

class IDCEngine:
    def __init__(self) -> None:
        self.client = IDCClient()
        tables = ("index", "collections_index", "ct_index", "mr_index", "pt_index", "seg_index",
                  "analysis_results_index")
        for table in tables[1:]:
            self.client.fetch_index(table)
        # idc-index re-registers every table on each query (~6 s overhead).
        # We register them once in our own DuckDB connection → queries take < 1 s.
        self.con = duckdb.connect()
        self._query_source = "local"
        for table in tables:
            df = getattr(self.client, table, None)
            if df is None:
                raise RuntimeError(f"IDC table '{table}' could not be loaded")
            # Copy into native DuckDB storage once: scanning pandas is ~50x slower.
            self.con.register("_tmp", df)
            self.con.execute(f'CREATE TABLE "{table}" AS SELECT * FROM _tmp')
            self.con.unregister("_tmp")
            if table != "index":          # idc-index only needs `index` to download;
                setattr(self.client, table, None)   # free the duplicate copy (saves RAM)

    # ---- basic info ------------------------------------------------------
    def version(self) -> str:
        return self.client.get_idc_version()

    def set_query_source(self, source: str) -> None:
        """local, api (IDC /v3/sql), or mcp (IDC /mcp run_sql)."""
        self._query_source = source if source in ("local", "api", "mcp") else "local"

    def sql(self, query: str) -> pd.DataFrame:
        if self._query_source == "local":
            return self.con.query(query).to_df()
        from query_source import remote_sql
        return remote_sql(query, self._query_source)

    def overview(self) -> dict:
        r = self.sql("""
            SELECT COUNT(DISTINCT collection_id) collections,
                   COUNT(DISTINCT collection_id || '/' || PatientID) patients,
                   COUNT(DISTINCT StudyInstanceUID) studies,
                   COUNT(*) series,
                   SUM(series_size_MB) / 1e6 size_TB
            FROM index
        """).iloc[0]
        return r.to_dict()

    # ---- choice lists (value + how many series have it) -----------------
    def options_cancer_types(self) -> pd.DataFrame:
        return self.sql("""
            WITH per_coll AS (
              SELECT collection_id, COUNT(*) n FROM index GROUP BY 1),
            t AS (
              SELECT TRIM(UNNEST(STRING_SPLIT(c.cancer_types, ','))) v, p.n
              FROM collections_index c JOIN per_coll p USING (collection_id)
              WHERE c.cancer_types IS NOT NULL)
            SELECT v AS "value", SUM(n)::BIGINT n FROM t WHERE v <> '' GROUP BY 1 ORDER BY n DESC
        """)

    def options_tumor_locations(self) -> pd.DataFrame:
        return self.sql("""
            WITH per_coll AS (
              SELECT collection_id, COUNT(*) n FROM index GROUP BY 1),
            t AS (
              SELECT TRIM(UNNEST(STRING_SPLIT(c.tumor_locations, ','))) v, p.n
              FROM collections_index c JOIN per_coll p USING (collection_id)
              WHERE c.tumor_locations IS NOT NULL)
            SELECT v AS "value", SUM(n)::BIGINT n FROM t WHERE v <> '' GROUP BY 1 ORDER BY n DESC
        """)

    def options_collections(self) -> pd.DataFrame:
        return self.sql("""
            SELECT i.collection_id AS "value", ANY_VALUE(c.collection_name) AS "name", COUNT(*) n
            FROM index i LEFT JOIN collections_index c USING (collection_id)
            GROUP BY 1 ORDER BY n DESC
        """)

    def options_simple(self, column: str, limit: int = 300) -> pd.DataFrame:
        allowed = {"Modality", "BodyPartExamined", "Manufacturer", "PatientSex"}
        if column not in allowed:
            raise ValueError(column)
        return self.sql(f"""
            SELECT {column} AS "value", COUNT(*) n FROM index
            WHERE {column} IS NOT NULL AND {column} <> ''
            GROUP BY 1 ORDER BY n DESC LIMIT {int(limit)}
        """)

    def options_ct_kvp(self) -> pd.DataFrame:
        return self.sql("""
            SELECT KVP AS "value", COUNT(*) n FROM ct_index WHERE KVP IS NOT NULL
            GROUP BY 1 HAVING COUNT(*) > 20 ORDER BY n DESC LIMIT 20
        """)

    def options_ct_kernels(self) -> pd.DataFrame:
        return self.sql("""
            SELECT k AS "value", COUNT(*) n
            FROM (SELECT UNNEST(ConvolutionKernel) k FROM ct_index)
            WHERE k IS NOT NULL AND k <> '' GROUP BY 1 ORDER BY n DESC LIMIT 60
        """)

    def options_mr_field(self) -> pd.DataFrame:
        return self.sql(f"""
            SELECT {_FIELD_T} AS "value", COUNT(*) n FROM mr_index mr
            WHERE mr.MagneticFieldStrength IS NOT NULL
            GROUP BY 1 HAVING COUNT(*) > 20 ORDER BY n DESC
        """)

    def options_mr_acq(self) -> pd.DataFrame:
        return self.sql("""
            SELECT MRAcquisitionType AS "value", COUNT(*) n FROM mr_index
            WHERE MRAcquisitionType IS NOT NULL GROUP BY 1 ORDER BY n DESC
        """)

    def options_pt_tracers(self) -> pd.DataFrame:
        return self.sql("""
            SELECT Radiopharmaceutical AS "value", COUNT(*) n FROM pt_index
            WHERE Radiopharmaceutical IS NOT NULL AND Radiopharmaceutical <> ''
            GROUP BY 1 ORDER BY n DESC LIMIT 40
        """)

    # ---- the core query ---------------------------------------------------
    def _from_where(self, r: Recipe) -> tuple[str, str]:
        joins = ["JOIN collections_index c USING (collection_id)"]
        where = ["1=1"]

        if r.cancer_types:
            where.append("(" + " OR ".join(
                f"c.cancer_types ILIKE {q('%' + v + '%')}" for v in r.cancer_types) + ")")
        if r.tumor_locations:
            where.append("(" + " OR ".join(
                f"c.tumor_locations ILIKE {q('%' + v + '%')}" for v in r.tumor_locations) + ")")
        if r.collections:
            where.append(f"i.collection_id IN {q_list(r.collections)}")
        if r.modalities:
            where.append(f"i.Modality IN {q_list(r.modalities)}")
        if r.body_parts:
            where.append(f"i.BodyPartExamined IN {q_list(r.body_parts)}")
        if r.manufacturers:
            where.append(f"i.Manufacturer IN {q_list(r.manufacturers)}")
        if r.sexes:
            where.append(f"i.PatientSex IN {q_list(r.sexes)}")
        if r.age_min is not None:
            where.append(f"{_AGE_YEARS} >= {int(r.age_min)}")
        if r.age_max is not None:
            where.append(f"{_AGE_YEARS} <= {int(r.age_max)}")
        if r.commercial_ok_only:
            where.append("i.license_short_name NOT ILIKE '%NC%' "
                         "AND i.license_short_name ILIKE 'CC BY%'")
        if r.with_segmentation_only:
            where.append("i.SeriesInstanceUID IN "
                         "(SELECT segmented_SeriesInstanceUID FROM seg_index)")

        if r.uses_ct():
            joins.append("JOIN ct_index ct USING (SeriesInstanceUID)")
            if r.ct_slice_min is not None:
                where.append(f"ct.SliceThickness >= {float(r.ct_slice_min)}")
            if r.ct_slice_max is not None:
                where.append(f"ct.SliceThickness <= {float(r.ct_slice_max)}")
            if r.ct_kvp:
                where.append("ct.KVP IN (" + ", ".join(str(float(v)) for v in r.ct_kvp) + ")")
            if r.ct_kernels:
                where.append(f"list_has_any(ct.ConvolutionKernel, [{', '.join(q(k) for k in r.ct_kernels)}])")

        if r.uses_mr():
            joins.append("JOIN mr_index mr USING (SeriesInstanceUID)")
            if r.mr_field_t:
                where.append(f"{_FIELD_T} IN (" + ", ".join(str(float(v)) for v in r.mr_field_t) + ")")
            if r.mr_acq_type:
                where.append(f"mr.MRAcquisitionType IN {q_list(r.mr_acq_type)}")
            if r.mr_slice_min is not None:
                where.append(f"mr.SliceThickness >= {float(r.mr_slice_min)}")
            if r.mr_slice_max is not None:
                where.append(f"mr.SliceThickness <= {float(r.mr_slice_max)}")

        if r.uses_pt():
            joins.append("JOIN pt_index pt USING (SeriesInstanceUID)")
            where.append(f"pt.Radiopharmaceutical IN {q_list(r.pt_tracers)}")

        return "FROM index i " + " ".join(joins), "WHERE " + " AND ".join(where)

    def summary(self, r: Recipe) -> dict:
        f, w = self._from_where(r)
        row = self.sql(f"""
            SELECT COUNT(DISTINCT i.collection_id) collections,
                   COUNT(DISTINCT i.collection_id || '/' || i.PatientID) patients,
                   COUNT(DISTINCT i.StudyInstanceUID) studies,
                   COUNT(*) series,
                   COALESCE(SUM(i.instanceCount), 0) images,
                   COALESCE(SUM(i.series_size_MB), 0) / 1000 size_GB
            {f} {w}
        """).iloc[0]
        return {k: (float(v) if k == "size_GB" else int(v)) for k, v in row.items()}

    def breakdown(self, r: Recipe, column: str, limit: int = 15) -> pd.DataFrame:
        allowed = {"i.collection_id", "i.Modality", "i.Manufacturer",
                   "i.license_short_name", "i.BodyPartExamined", "i.PatientSex"}
        if column not in allowed:
            raise ValueError(column)
        f, w = self._from_where(r)
        return self.sql(f"""
            SELECT COALESCE({column}, 'Unknown') AS "value", COUNT(*) series,
                   ROUND(SUM(i.series_size_MB) / 1000, 2) size_GB
            {f} {w} GROUP BY 1 ORDER BY series DESC LIMIT {int(limit)}
        """)

    def series(self, r: Recipe, limit: Optional[int] = 500) -> pd.DataFrame:
        f, w = self._from_where(r)
        extra = []
        if r.uses_ct():
            extra += ["ct.SliceThickness AS ct_slice_mm", "ct.KVP AS ct_kVp",
                      "array_to_string(ct.ConvolutionKernel, '/') AS ct_kernel"]
        if r.uses_mr():
            extra += [f"{_FIELD_T} AS mr_field_T", "mr.MRAcquisitionType AS mr_acq",
                      "mr.SliceThickness AS mr_slice_mm"]
        if r.uses_pt():
            extra += ["pt.Radiopharmaceutical AS pet_tracer"]
        extra_sql = (", " + ", ".join(extra)) if extra else ""
        lim = f"LIMIT {int(limit)}" if limit else ""
        return self.sql(f"""
            SELECT i.collection_id, i.PatientID, i.PatientSex, i.PatientAge,
                   i.Modality, i.BodyPartExamined, i.Manufacturer, i.ManufacturerModelName,
                   i.SeriesDescription, i.instanceCount AS images,
                   ROUND(i.series_size_MB, 1) AS size_MB, i.license_short_name AS license,
                   i.StudyInstanceUID, i.SeriesInstanceUID{extra_sql}
            {f} {w}
            ORDER BY i.collection_id, i.PatientID
            {lim}
        """)

    def series_uids(self, r: Recipe) -> list[str]:
        f, w = self._from_where(r)
        return self.sql(f"SELECT i.SeriesInstanceUID {f} {w}")["SeriesInstanceUID"].tolist()

    def sample_uids(self, r: Recipe, max_patients: int) -> tuple[list[str], float]:
        """All series of the first N patients (a small test set). Returns (uids, size_GB)."""
        f, w = self._from_where(r)
        df = self.sql(f"""
            WITH sel AS (SELECT i.collection_id, i.PatientID, i.SeriesInstanceUID, i.series_size_MB {f} {w}),
                 pats AS (SELECT DISTINCT collection_id, PatientID FROM sel
                          ORDER BY collection_id, PatientID LIMIT {int(max_patients)})
            SELECT s.SeriesInstanceUID, s.series_size_MB FROM sel s JOIN pats USING (collection_id, PatientID)
        """)
        return df["SeriesInstanceUID"].tolist(), float(df["series_size_MB"].sum()) / 1000

    # ---- extras --------------------------------------------------------
    @staticmethod
    def viewer_url(modality: str, study_uid: str, series_uid: str) -> str:
        """Browser viewer link (same URLs idc-index builds, without its slow lookup)."""
        base = "https://viewer.imaging.datacommons.cancer.gov"
        if modality in ("SM", "ANN"):
            return f"{base}/slim/studies/{study_uid}/series/{series_uid}"
        return f"{base}/v3/viewer/?StudyInstanceUIDs={study_uid}&initialSeriesInstanceUID={series_uid}"

    def manifest_s3(self, r: Recipe) -> str:
        """Plain-text manifest usable with `idc download <file>` or s5cmd."""
        f, w = self._from_where(r)
        urls = self.sql(f"SELECT DISTINCT i.series_aws_url {f} {w}")["series_aws_url"]
        return "\n".join(f"cp {u} ." for u in urls if isinstance(u, str))

    def citations(self, r: Recipe, max_collections: int = 30) -> list[str]:
        f, w = self._from_where(r)
        dois = self.sql(f"SELECT DISTINCT i.collection_id {f} {w}")["collection_id"].tolist()
        out: list[str] = []
        for cid in dois[:max_collections]:
            try:
                out.extend(self.client.citations_from_selection(collection_id=cid))
            except Exception as exc:  # network issues should not break the app
                out.append(f"[{cid}] citation unavailable: {exc}")
        return sorted(set(out))

    def download(self, series_uids: list[str], folder: str, layout: str,
                 source: str = "aws", progress_cb=None, batch: int = 10) -> None:
        """Download in small batches so the app can report progress and resume.

        idc-index only *logs* transfer failures, it does not raise. We listen to
        its log and raise DownloadError so the user is never told "done" wrongly.
        """
        total = len(series_uids)
        # An empty layout means "one folder". idc-index uses None for that, not "".
        dir_template = layout or None
        catcher = _ErrorCatcher()
        idc_logger = logging.getLogger("idc_index.index")
        idc_logger.addHandler(catcher)
        try:
            for start in range(0, total, batch):
                chunk = series_uids[start:start + batch]
                self.client.download_from_selection(
                    downloadDir=folder,
                    seriesInstanceUID=chunk,
                    dirTemplate=dir_template,
                    source_bucket_location=source,
                    use_s5cmd_sync=True,       # skips files already downloaded → resumable
                    show_progress_bar=False,
                    quiet=True,
                )
                if catcher.messages:
                    raise DownloadError("\n".join(catcher.messages))
                if progress_cb:
                    progress_cb(min(start + batch, total), total)
        finally:
            idc_logger.removeHandler(catcher)


class DownloadError(RuntimeError):
    """Raised when the file transfer reported an error."""


class _ErrorCatcher(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())
