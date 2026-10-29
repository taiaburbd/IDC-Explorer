"""
IDC Explorer – a point-and-click app for the NCI Imaging Data Commons.

Lets people with no programming knowledge find, preview, check the licence of,
and download public cancer imaging data (CT, MRI, PET, pathology…).

Start it with:   streamlit run app.py
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from query_source import LABELS, label as source_label, remote_version
from chat_memory import (ask_mcp, download_lines, format_answer, format_library_answer,
                         full_prompt, load_library, load_memory, match_library,
                         save_memory, selection_lines, sql_mcp, wants_download)
from idc_engine import (DIR_LAYOUTS, IMAGE_MODALITIES, MODALITY_LABELS,
                        IDCEngine, Recipe)

st.set_page_config(page_title="IDC Explorer", page_icon="🩻", layout="wide")


def run_download(recipe: Recipe, uids: list[str], size_gb: float, existing: Path,
                 layout_name: str, source: str) -> None:
    """Download with a progress bar. Used by the Download tab and the chat."""
    existing.mkdir(parents=True, exist_ok=True)
    before = tree_bytes(existing)
    expected = max(size_gb * 1e9, 1.0)
    state = {"done": 0, "total": max(len(uids), 1), "error": None, "finished": False}
    lock = threading.Lock()

    def cb(done, total):
        with lock:
            state["done"] = done
            state["total"] = total or 1

    def worker():
        try:
            engine.download(uids, str(existing), DIR_LAYOUTS[layout_name], source, cb)
        except Exception as exc:
            state["error"] = exc
        finally:
            state["finished"] = True

    threading.Thread(target=worker, daemon=True).start()
    bar = st.progress(0, text="Starting download…")
    while not state["finished"]:
        with lock:
            done, total = state["done"], state["total"]
        written = max(0, tree_bytes(existing) - before)
        byte_frac = min(written / expected, 0.99)
        series_frac = min(done / total, 1.0) if total else 0.0
        pct = int(min(99, round(max(byte_frac, series_frac) * 100)))
        bar.progress(
            pct,
            text=(f"{human_size(written / 1e9)} written of about {human_size(size_gb)}"
                  f" · {done:,} of {total:,} scans"),
        )
        time.sleep(0.4)
    if state["error"] is not None:
        bar.progress(0, text="Download stopped")
        st.error("The download stopped. Press *Start download* again: files already "
                 "downloaded are skipped, so it continues where it left off.")
        with st.expander("Technical details (for your IT contact)"):
            st.exception(state["error"])
    else:
        written = max(0, tree_bytes(existing) - before)
        bar.progress(100, text=f"Done · {human_size(written / 1e9)} written")
        (existing / "idc_search.json").write_text(recipe.to_json())
        st.success(f"✅ Finished. Your files are in **{existing}**. "
                   "Your search was saved there too (idc_search.json) so it can be repeated.")
        st.balloons()


# ==========================================================================
# Data loading (cached: runs once per app start)
# ==========================================================================

@st.cache_resource(show_spinner="Loading the IDC catalogue (first start can take a minute)…")
def get_engine() -> IDCEngine:
    return IDCEngine()


@st.cache_data(show_spinner=False)
def load_options() -> dict:
    e = get_engine()
    # Choice lists stay on the local catalogue. The query-source setting
    # applies to results, chat, and the SQL playground after this cache.
    previous = e._query_source
    e.set_query_source("local")
    try:
        return _option_lists(e)
    finally:
        e.set_query_source(previous)


def _option_lists(e: IDCEngine) -> dict:
    return {
        "version": e.version(),
        "overview": e.overview(),
        "cancer": e.options_cancer_types(),
        "location": e.options_tumor_locations(),
        "collections": e.options_collections(),
        "modality": e.options_simple("Modality"),
        "body": e.options_simple("BodyPartExamined"),
        "manufacturer": e.options_simple("Manufacturer"),
        "ct_kvp": e.options_ct_kvp(),
        "ct_kernel": e.options_ct_kernels(),
        "mr_field": e.options_mr_field(),
        "mr_acq": e.options_mr_acq(),
        "pt_tracer": e.options_pt_tracers(),
    }


def tree_bytes(path: Path) -> int:
    """Bytes in this folder and every folder under it. The library only counts the top folder."""
    total = 0
    if not path.exists():
        return 0
    for dirpath, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                continue
    return total


def human_size(gb: float) -> str:
    if gb < 1:
        return f"{gb * 1000:,.0f} MB"
    if gb < 1000:
        return f"{gb:,.1f} GB"
    return f"{gb / 1000:,.2f} TB"


def download_time(gb: float, mbit: float = 100) -> str:
    sec = gb * 8000 / mbit
    if sec < 90:
        return "about a minute"
    if sec < 3600:
        return f"about {sec / 60:,.0f} minutes"
    if sec < 86400 * 2:
        return f"about {sec / 3600:,.1f} hours"
    return f"about {sec / 86400:,.0f} days"


def with_counts(df: pd.DataFrame, label_fn=None):
    """Return (values, format_func) so a multiselect shows 'Label (12,345)'."""
    counts = dict(zip(df["value"], df["n"]))

    def fmt(v):
        name = label_fn(v) if label_fn else str(v)
        return f"{name}  ({counts.get(v, 0):,} scans)"
    return list(df["value"]), fmt


# ==========================================================================
# Ready-made searches for people who don't know where to start
# ==========================================================================

PRESETS = {
    "🧠 Brain MRI, 3 Tesla, with tumour outlines": dict(
        f_location=["Brain"], f_modality=["MR"], f_mr_field=[3.0], f_seg=True),
    "🫁 Lung CT, thin slices (≤ 1.5 mm), commercial use allowed": dict(
        f_cancer=["Lung Cancer"], f_modality=["CT"], f_ct_on=True,
        f_ct_slice=(0.0, 1.5), f_commercial=True),
    "🎀 Breast MRI": dict(f_location=["Breast"], f_modality=["MR"]),
    "♂️ Prostate MRI with outlines": dict(f_location=["Prostate"], f_modality=["MR"], f_seg=True),
    "🔥 PET scans": dict(f_modality=["PT"]),
    "🔬 Pathology slides": dict(f_modality=["SM"]),
}

DEFAULTS = dict(
    f_cancer=[], f_location=[], f_modality=[], f_sex=[], f_age_on=False, f_age=(18, 90),
    f_commercial=False, f_seg=False, f_collections=[], f_manufacturer=[], f_body=[],
    f_ct_on=False, f_ct_slice=(0.0, 5.0), f_ct_kvp=[], f_ct_kernel=[],
    f_mr_field=[], f_mr_acq=[], f_mr_slice_on=False, f_mr_slice=(0.0, 5.0),
    f_pt_tracer=[], f_show_derived=False,
)


def reset_filters():
    for k, v in DEFAULTS.items():
        st.session_state[k] = v


def apply_preset(name: str):
    reset_filters()
    for k, v in PRESETS[name].items():
        st.session_state[k] = v


def apply_recipe(r: Recipe):
    reset_filters()
    s = st.session_state
    s.f_cancer, s.f_location, s.f_collections = r.cancer_types, r.tumor_locations, r.collections
    s.f_modality, s.f_body, s.f_manufacturer, s.f_sex = r.modalities, r.body_parts, r.manufacturers, r.sexes
    if r.age_min is not None or r.age_max is not None:
        s.f_age_on, s.f_age = True, (r.age_min or 0, r.age_max or 100)
    s.f_commercial, s.f_seg = r.commercial_ok_only, r.with_segmentation_only
    if r.ct_slice_min is not None or r.ct_slice_max is not None:
        s.f_ct_on, s.f_ct_slice = True, (r.ct_slice_min or 0.0, r.ct_slice_max or 10.0)
    s.f_ct_kvp, s.f_ct_kernel = r.ct_kvp, r.ct_kernels
    s.f_mr_field, s.f_mr_acq = r.mr_field_t, r.mr_acq_type
    if r.mr_slice_min is not None or r.mr_slice_max is not None:
        s.f_mr_slice_on, s.f_mr_slice = True, (r.mr_slice_min or 0.0, r.mr_slice_max or 10.0)
    s.f_pt_tracer = r.pt_tracers
    if any(m not in IMAGE_MODALITIES for m in r.modalities):
        s.f_show_derived = True


def load_uploaded_recipe():
    up = st.session_state.get("f_upload")
    st.session_state["_bad_upload"] = False
    if up is None:
        return
    try:
        apply_recipe(Recipe.from_json(up.getvalue().decode()))
    except Exception:
        st.session_state["_bad_upload"] = True


for key, val in DEFAULTS.items():
    st.session_state.setdefault(key, val)


def recipe_from_state() -> Recipe:
    s = st.session_state
    mods = s.f_modality
    r = Recipe(
        cancer_types=s.f_cancer, tumor_locations=s.f_location, collections=s.f_collections,
        modalities=mods, body_parts=s.f_body, manufacturers=s.f_manufacturer, sexes=s.f_sex,
        commercial_ok_only=s.f_commercial, with_segmentation_only=s.f_seg,
    )
    if s.f_age_on:
        r.age_min, r.age_max = s.f_age
    if "CT" in mods:
        if s.f_ct_on:
            r.ct_slice_min, r.ct_slice_max = s.f_ct_slice
        r.ct_kvp, r.ct_kernels = s.f_ct_kvp, s.f_ct_kernel
    if "MR" in mods:
        r.mr_field_t, r.mr_acq_type = s.f_mr_field, s.f_mr_acq
        if s.f_mr_slice_on:
            r.mr_slice_min, r.mr_slice_max = s.f_mr_slice
    if "PT" in mods:
        r.pt_tracers = s.f_pt_tracer
    return r


# ==========================================================================
# Load data
# ==========================================================================

try:
    engine = get_engine()
    opts = load_options()
except Exception as exc:  # most likely no internet on first start
    st.error("Could not load the IDC catalogue. Please check your internet connection "
             "and restart the app.")
    st.exception(exc)
    st.stop()


# ==========================================================================
# Sidebar: the filters
# ==========================================================================

with st.sidebar:
    st.header("Query source")
    st.radio(
        "Where catalogue queries run",
        list(LABELS),
        format_func=source_label,
        key="query_source",
        help="Local reads the catalogue already loaded on this computer. "
             "Remote IDC API sends the SQL to "
             "https://api.imaging.datacommons.cancer.gov/v3/sql. "
             "Remote IDC MCP sends the same SQL to the run_sql tool at "
             "https://api.imaging.datacommons.cancer.gov/mcp. "
             "A typed question is still turned into SQL on this computer; "
             "only the query itself uses the source you pick. "
             "Downloads and the viewer do not change. "
             "The lists in this panel stay counted from the local catalogue.",
    )
    engine.set_query_source(st.session_state.query_source)
    if st.session_state.query_source == "local":
        st.caption("Queries stay on this computer. Nothing is sent to the IDC API or MCP.")
    else:
        st.caption("Results, chat, and SQL call the public IDC service. "
                   "A selection larger than 10,000 scans cannot be listed this way.")

    st.header("🔎 What are you looking for?")
    st.caption("Pick as few or as many as you like. Every choice narrows the results.")

    with st.expander("⚡ Quick start – ready-made searches"):
        for name in PRESETS:
            st.button(name, on_click=apply_preset, args=(name,), width="stretch")

    st.subheader("1 · Disease and body area")
    vals, fmt = with_counts(opts["cancer"])
    st.multiselect("Cancer type", vals, format_func=fmt, key="f_cancer",
                   placeholder="Any cancer type")
    vals, fmt = with_counts(opts["location"])
    st.multiselect("Organ / tumour location", vals, format_func=fmt, key="f_location",
                   placeholder="Any location")

    st.subheader("2 · Type of images")
    st.checkbox("Also show derived data (outlines, reports, annotations)", key="f_show_derived",
                help="Segmentations, radiotherapy contours, structured reports. "
                     "Most people only need the images themselves.")
    mod_df = opts["modality"]
    if not st.session_state.f_show_derived:
        mod_df = mod_df[mod_df["value"].isin(IMAGE_MODALITIES)]
        st.session_state.f_modality = [m for m in st.session_state.f_modality
                                       if m in IMAGE_MODALITIES]
    vals, fmt = with_counts(mod_df, lambda v: f"{MODALITY_LABELS.get(v, v)} [{v}]")
    st.multiselect("Imaging modality", vals, format_func=fmt, key="f_modality",
                   placeholder="Any type")
    st.checkbox("Only scans that have organ/tumour outlines", key="f_seg",
                help="Useful for training AI models: keeps only images for which a "
                     "segmentation (outline drawn by an expert or an AI) exists.")

    mods = st.session_state.f_modality
    if any(m in mods for m in ("CT", "MR", "PT")):
        st.subheader("3 · Scanner settings")
    if "CT" in mods:
        with st.expander("CT settings", expanded=True):
            st.checkbox("Filter by slice thickness", key="f_ct_on",
                        help="Thinner slices = more detail. 1 mm is high resolution, 5 mm is standard.")
            if st.session_state.f_ct_on:
                st.slider("Slice thickness (mm)", 0.0, 10.0, step=0.25, key="f_ct_slice")
            vals, fmt = with_counts(opts["ct_kvp"], lambda v: f"{v:g} kV")
            st.multiselect("Tube voltage", vals, format_func=fmt, key="f_ct_kvp",
                           help="120 kV is standard; 80–100 kV is often low-dose or paediatric.")
            vals, fmt = with_counts(opts["ct_kernel"])
            st.multiselect("Reconstruction kernel", vals, format_func=fmt, key="f_ct_kernel",
                           help="Soft kernels (e.g. B30f, STANDARD) for soft tissue; "
                                "sharp kernels (e.g. B70f, LUNG, BONE) for lungs and bone.")
    if "MR" in mods:
        with st.expander("MRI settings", expanded=True):
            vals, fmt = with_counts(opts["mr_field"], lambda v: f"{v:g} Tesla")
            st.multiselect("Magnet strength", vals, format_func=fmt, key="f_mr_field",
                           help="3 T gives sharper images than 1.5 T.")
            vals, fmt = with_counts(opts["mr_acq"], lambda v: {"2D": "2D (slice by slice)",
                                                              "3D": "3D (volume)"}.get(v, v))
            st.multiselect("Acquisition", vals, format_func=fmt, key="f_mr_acq")
            st.checkbox("Filter by slice thickness", key="f_mr_slice_on")
            if st.session_state.f_mr_slice_on:
                st.slider("Slice thickness (mm)", 0.0, 10.0, step=0.25, key="f_mr_slice")
    if "PT" in mods:
        with st.expander("PET settings", expanded=True):
            vals, fmt = with_counts(opts["pt_tracer"])
            st.multiselect("Tracer (radiopharmaceutical)", vals, format_func=fmt, key="f_pt_tracer")

    st.subheader("4 · Patients")
    st.multiselect("Sex", ["F", "M"], key="f_sex",
                   format_func=lambda v: {"F": "Female", "M": "Male"}[v], placeholder="Any")
    st.checkbox("Filter by age", key="f_age_on")
    if st.session_state.f_age_on:
        st.slider("Age (years)", 0, 100, key="f_age")

    st.subheader("5 · Usage rights")
    st.toggle("Only data I may use commercially", key="f_commercial",
              help="Keeps only CC BY licensed data (commercial use allowed with attribution) "
                   "and removes CC BY-NC (non-commercial only).")

    with st.expander("Advanced filters"):
        coll = opts["collections"]
        names = dict(zip(coll["value"], coll["name"]))
        vals, fmt = with_counts(coll, lambda v: f"{names.get(v) or v}")
        st.multiselect("Specific collections (datasets)", vals, format_func=fmt, key="f_collections")
        vals, fmt = with_counts(opts["manufacturer"])
        st.multiselect("Scanner manufacturer", vals, format_func=fmt, key="f_manufacturer")
        vals, fmt = with_counts(opts["body"])
        st.multiselect("Body part (as written by the scanner)", vals, format_func=fmt, key="f_body",
                       help="Often empty in the data; 'Organ / tumour location' above is more reliable.")

    st.divider()
    st.button("↺ Clear all choices", on_click=reset_filters, width="stretch")

    recipe = recipe_from_state()
    st.download_button("💾 Save this search", recipe.to_json(), file_name="idc_search.json",
                       mime="application/json", width="stretch",
                       help="Keep your choices in a small file to reopen later or share with a colleague.")
    st.file_uploader("📂 Open a saved search", type="json", key="f_upload",
                     on_change=load_uploaded_recipe)
    if st.session_state.get("_bad_upload"):
        st.error("This file is not a valid saved search.")


# ==========================================================================
# Main page
# ==========================================================================

ov = opts["overview"]
st.title("🩻 IDC Explorer")
_source = st.session_state.get("query_source", "local")
_source_note = f"Queries: {source_label(_source)}"
if _source != "local":
    try:
        _source_note += f" · remote release {remote_version()}"
    except Exception:
        _source_note += " · remote release unavailable"
st.caption(f"Free public cancer imaging from the NCI Imaging Data Commons · local data release "
           f"**{opts['version']}** · {ov['collections']:.0f} datasets · {ov['patients']:,.0f} patients · "
           f"{ov['size_TB']:,.0f} TB · {_source_note}")


# ==========================================================================
# Assistant chat: one box on every page, answered by the MCP `ask` tool
# ==========================================================================

st.session_state.setdefault("local_memory", load_memory())
st.session_state.setdefault("chat", [])
LIBRARY = load_library()
LIBRARY_BY_ID = {item["id"]: item for item in LIBRARY}
chat_box = st.container()   # conversation shows here, above the tabs


# ==========================================================================
# SQL playground: anyone can query the catalogue, through the MCP `query_index` tool
# ==========================================================================

SQL_EXAMPLES = {
    "Patients and size per dataset": """SELECT collection_id,
       COUNT(DISTINCT PatientID) AS patients,
       COUNT(*) AS series,
       ROUND(SUM(series_size_MB) / 1000, 1) AS size_GB
FROM index
GROUP BY collection_id
ORDER BY patients DESC""",
    "Imaging types (modalities)": """SELECT Modality, COUNT(*) AS series, COUNT(DISTINCT collection_id) AS datasets
FROM index
GROUP BY Modality
ORDER BY series DESC""",
    "Licences": """SELECT license_short_name, COUNT(*) AS series,
       ROUND(SUM(series_size_MB) / 1e6, 2) AS size_TB
FROM index
GROUP BY 1
ORDER BY series DESC""",
    "Datasets about a cancer (edit 'Lung')": """SELECT collection_id, collection_name, subjects, cancer_types, tumor_locations
FROM collections_index
WHERE cancer_types ILIKE '%Lung%'
ORDER BY subjects DESC""",
    "Brain MRI at 3 Tesla": """SELECT i.collection_id, i.PatientID, i.SeriesDescription,
       ROUND(i.series_size_MB, 1) AS size_MB, i.license_short_name
FROM index i
JOIN mr_index mr USING (SeriesInstanceUID)
JOIN collections_index c USING (collection_id)
WHERE c.tumor_locations ILIKE '%Brain%'
  AND mr.MagneticFieldStrength IN (3, 30000)
  AND i.analysis_result_id IS NULL""",
    "Thin-slice CT (≤ 1.5 mm)": """SELECT i.collection_id, COUNT(*) AS series
FROM index i
JOIN ct_index ct USING (SeriesInstanceUID)
WHERE ct.SliceThickness <= 1.5
GROUP BY 1
ORDER BY series DESC""",
    "What the segmentations outline": """SELECT outlined, AlgorithmType, COUNT(*) AS seg_series
FROM (SELECT UNNEST(SegmentedPropertyType_CodeMeanings) AS outlined, AlgorithmType
      FROM seg_index)
GROUP BY 1, 2
ORDER BY seg_series DESC
LIMIT 50""",
    "Analysis results (AI / expert derived data)": """SELECT analysis_result_id, analysis_result_title, subjects, modalities, license_short_name
FROM analysis_results_index
ORDER BY subjects DESC""",
    "Patients by sex and age band": """SELECT PatientSex,
       (TRY_CAST(SUBSTR(PatientAge, 1, 3) AS INTEGER) // 10) * 10 AS age_from,
       COUNT(DISTINCT collection_id || '/' || PatientID) AS patients
FROM index
WHERE PatientAge LIKE '%Y'
GROUP BY 1, 2
ORDER BY 1, 2""",
}
SQL_TABLES = ("index (one row per scan) · collections_index (datasets) · ct_index · mr_index · "
              "pt_index (scanner settings) · seg_index (outlines) · analysis_results_index")


def load_sql_example():
    st.session_state.sql_text = SQL_EXAMPLES[st.session_state.sql_example]


def sql_playground() -> None:
    s = st.session_state
    s.setdefault("sql_text", SQL_EXAMPLES["Patients and size per dataset"])
    with st.expander("🧪 SQL playground – ask the data directly with SQL", expanded=bool(s.get("sql_result"))):
        st.caption("Read-only: one SELECT (or WITH) query at a time, up to 5,000 rows. "
                   f"It runs on {source_label(st.session_state.get('query_source', 'local'))}. "
                   "Tables: " + SQL_TABLES)
        st.selectbox("Start from an example", list(SQL_EXAMPLES), key="sql_example",
                     on_change=load_sql_example, index=None, placeholder="Pick an example query…")
        st.text_area("SQL query", key="sql_text", height=180)
        if st.button("▶ Run query", type="primary"):
            try:
                with st.spinner("Running…"):
                    s.sql_result = sql_mcp(s.sql_text, engine.sql)
                s.sql_error = None
            except Exception as exc:
                s.sql_result, s.sql_error = None, str(exc)
        if s.get("sql_error"):
            st.error(f"The query did not run: {s.sql_error}")
        result = s.get("sql_result")
        if result is not None:
            frame = pd.DataFrame(result["rows"])
            st.caption(f"{len(frame):,} rows" + (" (first 5,000 only)" if result["truncated"] else ""))
            st.dataframe(frame, hide_index=True, width="stretch")
            if len(frame):
                st.download_button("Save as spreadsheet (CSV)", frame.to_csv(index=False),
                                   file_name="idc_query.csv", mime="text/csv")
            python = (result.get("work") or {}).get("python")
            if python:
                with st.expander("Run the same query in Python"):
                    st.code(python, language="python")


sql_playground()


def ask_again(question: str):
    st.session_state._ask_now = question


def ask_library(qid: str):
    st.session_state._ask_now = LIBRARY_BY_ID[qid]["question"]


def ask_typed():
    """The prompt box: a picked suggestion or new text (Enter) is asked, then the box clears."""
    picked = st.session_state.get("chat_pick")
    if picked:
        st.session_state._ask_now = picked
    st.session_state.chat_pick = None


def clear_chat():
    st.session_state.chat = []


@st.dialog("Ask the IDC assistant", width="large")
def confirm_and_ask():
    s = st.session_state
    if s.get("pending_answer") is None:
        st.warning("Are you sure you want to send this prompt?")
        st.code(s.pending_prompt, language=None)
        yes, no = st.columns(2)
        if yes.button("Yes, send it", type="primary", width="stretch"):
            local = s.get("pending_local")
            item = s.get("pending_library")
            try:
                with st.spinner(f"Querying {source_label(st.session_state.get('query_source', 'local'))}…"):
                    if item:   # a library question: its checked SQL, through `query_index`
                        text = format_library_answer(item, sql_mcp(item["sql"], engine.sql, 200))
                    else:
                        text = format_answer(local, ask_mcp(s.pending_prompt, engine.sql))
            except Exception as exc:
                text = (local + "\n\n" if local else "") + f"The assistant could not run that query: {exc}"
            s.chat.append({"role": "user", "text": s.pending_prompt})
            s.chat.append({"role": "assistant", "text": text})
            s.local_memory = save_memory(s.pending_question, s.pending_prompt, text[:500])
            s.pending_answer = text
            st.rerun(scope="fragment")
        if no.button("No, go back", width="stretch"):
            st.rerun()
    else:
        st.markdown(s.pending_answer)
        if s.get("pending_wants_download"):
            chat_download(s.get("pending_download"))
        if st.button("Close", type="primary", width="stretch"):
            s.pending_answer = None
            st.rerun()


def chat_download(plan: dict | None) -> None:
    """Offer the download only when the question asked for one."""
    st.divider()
    if plan is None:
        st.info("To download, first choose what you need in the left panel.")
        return
    st.markdown(f"**Download:** {plan['what']} · {plan['scans']:,} scans · "
                f"{human_size(plan['size_gb'])} → `{plan['existing']}`  \n"
                "Change the amount, folder or server on the ⬇️ Download tab.")
    if plan["size_gb"] * 1.05 > plan["free_gb"]:
        st.error("Not enough free disk space. Choose a smaller selection or another folder/disk.")
        return
    agree = st.checkbox("I have checked the licences (see the 📜 tab) and will cite the data as required.",
                        key="chat_agree")
    if st.button("⬇️ Start this download", disabled=not agree or not plan["uids"], width="stretch"):
        run_download(plan["recipe"], plan["uids"], plan["size_gb"], plan["existing"],
                     plan["layout_name"], plan["source"])


def render_chat(lines: list[str], local: str | None, download: dict | None = None) -> None:
    """Draw the conversation and the chat box.

    `lines` describe the selection on screen. `download` (the plan from the Download tab)
    is only added to the prompt when the question asks to download.
    """
    s = st.session_state
    with chat_box:
        if LIBRARY:
            with st.expander(f"💡 Not sure what to ask? {len(LIBRARY)} suggested questions"):
                st.caption("Each one is answered with a checked query, so the answer is always right.")
                topics = list(dict.fromkeys(item["topic"] for item in LIBRARY))
                topic = st.radio("Topic", topics, horizontal=True, key="suggest_topic",
                                 label_visibility="collapsed")
                for item in LIBRARY:
                    if item["topic"] == topic:
                        st.button(item["question"], key=f"sugg_{item['id']}",
                                  on_click=ask_library, args=(item["id"],))
        if s.chat or s.local_memory:
            title = f"💬 Conversation with the assistant ({len(s.chat) // 2})"
            with st.expander(title, expanded=bool(s.chat)):
                for message in s.chat:
                    with st.chat_message(message["role"]):
                        st.markdown(message["text"])
                if s.chat:
                    st.button("Clear conversation", on_click=clear_chat)
                if s.local_memory:
                    st.caption("Asked before on this computer. Click one to ask it again.")
                    for i, item in enumerate(s.local_memory[:6]):
                        label = item["question"]
                        if item.get("at"):
                            label = f"{label}  ·  {item['at']}"
                        st.button(label, key=f"mem_{i}", on_click=ask_again, args=(item["question"],))

    # The prompt box, pinned to the bottom. As you type, matching suggestions (asked before on
    # this computer, then the question library) appear; Enter sends your own words as they are.
    asked = [m["question"] for m in s.local_memory
             if len(m["question"]) <= 120 and "\n" not in m["question"]]   # skip pasted blocks
    suggestions = list(dict.fromkeys(asked + [item["question"] for item in LIBRARY]))
    with st.bottom:
        st.selectbox("Ask the IDC assistant", suggestions, index=None, key="chat_pick",
                     accept_new_options=True, on_change=ask_typed, label_visibility="collapsed",
                     placeholder="💬 Ask the IDC assistant – type, and matching questions appear "
                                 "(Enter sends your own)")
    question = (s.pop("_ask_now", None) or "").strip()
    if question:
        item = match_library(LIBRARY, question)
        if item:
            s.pending_question = question
            s.pending_prompt = f"{item['question']}\n\nChecked query from the question library:\n{item['sql']}"
            s.pending_local, s.pending_library = None, item
            s.pending_wants_download, s.pending_download = False, None
            s.pending_answer = None
            confirm_and_ask()
            return
        s.pending_library = None
        wanted = wants_download(question)
        if wanted and download:
            lines = lines + download["lines"]
            local = f"{local} {download['local']}"
        s.pending_question = question
        s.pending_prompt = full_prompt(question, lines)
        s.pending_local = local
        s.pending_wants_download = wanted
        s.pending_download = download
        s.pending_answer = None
        confirm_and_ask()


recipe = recipe_from_state()
if recipe.is_empty():
    st.info("👈 **Start by choosing what you need in the left panel**, or open "
            "**⚡ Quick start** for a ready-made search. "
            "You can also type a question in the **chat box at the bottom** of the page at any time.")
    render_chat([], None)
    st.stop()

summary = engine.summary(recipe)
if summary["series"] == 0:
    st.warning("No scans match all your choices. Try removing one of them.")
    render_chat([], "Your current filters match no scans.")
    st.stop()

c = st.columns(5)
c[0].metric("Patients", f"{summary['patients']:,}")
c[1].metric("Scans (series)", f"{summary['series']:,}")
c[2].metric("Images", f"{summary['images']:,}")
c[3].metric("Datasets", f"{summary['collections']:,}")
c[4].metric("Total size", human_size(summary["size_GB"]))

lic = engine.breakdown(recipe, "i.license_short_name")
nc = lic[lic["value"].str.contains("NC", na=False)]
if len(nc):
    st.warning(f"⚠️ {int(nc['series'].sum()):,} of these scans are **non-commercial only** "
               "(CC BY-NC). Turn on *Only data I may use commercially* if you need them for a product.")

tab_res, tab_prev, tab_dl, tab_lic, tab_help = st.tabs(
    ["📊 Overview", "👁️ Browse & preview", "⬇️ Download",
     "📜 Licences & citations", "❓ Help"])

# ---------------------------------------------------------------- overview
with tab_res:
    st.write(f"You selected **{summary['series']:,} scans** from **{summary['patients']:,} patients**, "
             f"in **{summary['collections']} datasets**. Downloading everything is "
             f"**{human_size(summary['size_GB'])}** ({download_time(summary['size_GB'])} on a 100 Mbit/s connection).")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**By dataset**")
        st.bar_chart(engine.breakdown(recipe, "i.collection_id"), x="value", y="series",
                     horizontal=True, x_label="Number of scans", y_label="")
        st.markdown("**By imaging type**")
        st.bar_chart(engine.breakdown(recipe, "i.Modality"), x="value", y="series",
                     horizontal=True, x_label="Number of scans", y_label="")
    with col2:
        st.markdown("**By scanner manufacturer**")
        st.bar_chart(engine.breakdown(recipe, "i.Manufacturer"), x="value", y="series",
                     horizontal=True, x_label="Number of scans", y_label="")
        st.markdown("**By sex**")
        st.bar_chart(engine.breakdown(recipe, "i.PatientSex"), x="value", y="series",
                     horizontal=True, x_label="Number of scans", y_label="")

# ---------------------------------------------------------------- preview
with tab_prev:
    st.write("Click **Open** to look at a scan in your web browser – nothing is downloaded. "
             "The list shows up to 500 scans.")
    df = engine.series(recipe, limit=500)
    df.insert(0, "View", [engine.viewer_url(m, st_, se) for m, st_, se in
                          zip(df["Modality"], df["StudyInstanceUID"], df["SeriesInstanceUID"])])
    st.dataframe(
        df, width="stretch", hide_index=True, height=520,
        column_config={
            "View": st.column_config.LinkColumn("View", display_text="Open ↗"),
            "collection_id": "Dataset", "PatientSex": "Sex", "PatientAge": "Age",
            "BodyPartExamined": "Body part", "ManufacturerModelName": "Scanner model",
            "SeriesDescription": "Description", "size_MB": st.column_config.NumberColumn("Size (MB)"),
        })
    if summary["series"] > 200_000:
        st.caption("The full list is too large for a spreadsheet; narrow your search to export it.")
    elif st.button("📄 Prepare the full list as a spreadsheet (CSV)"):
        st.download_button("Save spreadsheet", engine.series(recipe, limit=None).to_csv(index=False),
                           file_name="idc_selection.csv", mime="text/csv", type="primary")

# ---------------------------------------------------------------- download
with tab_dl:
    st.write("Files are standard **DICOM** medical images. They are saved on this computer.")
    folder = st.text_input("Save to folder", value=str(Path.home() / "IDC_downloads"), key="dl_folder")
    layout_name = st.selectbox("How to organise the folders", list(DIR_LAYOUTS), key="dl_layout")
    how_much = st.radio("What to download",
                        ["A small test sample first (recommended)", "Everything I selected"],
                        key="dl_how")
    n_pat = 5
    if how_much.startswith("A small"):
        n_pat = st.number_input("Number of patients in the sample", 1, 500, 5, key="dl_n_pat")
        uids, size_gb = engine.sample_uids(recipe, int(n_pat))
    else:
        uids, size_gb = engine.series_uids(recipe), summary["size_GB"]

    existing = Path(folder).expanduser()
    probe = existing
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    free_gb = shutil.disk_usage(probe).free / 1e9

    st.info(f"This will download **{len(uids):,} scans · {human_size(size_gb)}** "
            f"({download_time(size_gb)} at 100 Mbit/s). Free space on this disk: **{human_size(free_gb)}**.")
    if size_gb * 1.05 > free_gb:
        st.error("Not enough free disk space. Choose a smaller selection or another folder/disk.")
    source = st.radio("Download server", ["aws", "gcs"], horizontal=True,
                      format_func=lambda v: {"aws": "Amazon (default)", "gcs": "Google"}[v],
                      help="Both are free and contain the same files. Switch if one is slow.",
                      key="dl_source")
    agree = st.checkbox("I have checked the licences (see the 📜 tab) and will cite the data as required.")

    if st.button("⬇️ Start download", type="primary",
                 disabled=not agree or size_gb * 1.05 > free_gb or not uids):
        run_download(recipe, uids, size_gb, existing, layout_name, source)

    with st.expander("Very large download? Use a download list instead"):
        st.write("For selections of hundreds of GB, it is more reliable to give this list to "
                 "a download tool. Send it to your IT contact, or run in a terminal: "
                 "`idc download idc_manifest.s5cmd --download-dir <folder>`")
        if st.button("Prepare download list"):
            st.download_button("Save download list (manifest)", engine.manifest_s3(recipe),
                               file_name="idc_manifest.s5cmd", type="primary")

# ---------------------------------------------------------------- licences
with tab_lic:
    st.markdown("""
**What the licences mean (not legal advice):**
- **CC BY** – free to use, including in commercial products, as long as you **credit** the source.
- **CC BY-NC** – free for research and teaching, **not for commercial use**.
- **NLM Terms and Conditions** – read the terms of that dataset before use.
""")
    st.dataframe(lic.rename(columns={"value": "Licence", "series": "Scans", "size_GB": "Size (GB)"}),
                 hide_index=True, width="stretch")
    st.markdown("**Licences per dataset**")
    f, w = engine._from_where(recipe)
    st.dataframe(engine.sql(f"""
        SELECT i.collection_id AS Dataset, i.license_short_name AS Licence,
               COUNT(*) AS Scans, ANY_VALUE(i.source_DOI) AS DOI
        {f} {w} GROUP BY 1, 2 ORDER BY 1"""), hide_index=True, width="stretch")
    if st.button("Generate citations for my selection"):
        with st.spinner("Looking up citations…"):
            cites = engine.citations(recipe)
        text = "\n\n".join(cites)
        st.text_area("Copy these into your paper or product documentation", text, height=300)
        st.download_button("Save citations", text, file_name="idc_citations.txt")
    st.caption("Also cite IDC itself: Fedorov A. et al. National Cancer Institute Imaging Data "
               "Commons. RadioGraphics 43(12), 2023. https://doi.org/10.1148/rg.230180")

# ---------------------------------------------------------------- help
with tab_help:
    st.markdown("""
### How to use
1. **Choose** what you need in the left panel – start with a *Quick start* if unsure.
2. **Check** the numbers and charts in *Overview*.
3. **Look** at a few scans in *Browse & preview* (opens in your browser).
4. **Check the licence** in *Licences & citations*.
5. **Download** – try a small sample first. The bar follows the files as they land on disk.
6. **SQL playground** (top of the page) – pick an example or write your own read-only SQL query,
   run it, and save the result as a spreadsheet.
7. **Ask** – type a question in the chat box at the bottom of any page. After you confirm,
   the question is turned into SQL on this computer and that SQL runs on the query source
   you picked in the left panel. The conversation shows at the top of the page; past
   questions are saved on this computer.
8. **Query source** (top of the left panel) – Local keeps every query on this computer.
   Remote IDC API sends SQL to `api.imaging.datacommons.cancer.gov/v3/sql`.
   Remote IDC MCP sends the same SQL to the `run_sql` tool at
   `api.imaging.datacommons.cancer.gov/mcp`. Downloads and the viewer stay the same.
9. **Save this search** (left panel) so you or a colleague can repeat it exactly.

### Words you may see
- **Dataset / collection** – a group of scans published together by a research project.
- **Scan / series** – one set of images taken in one go (e.g. one CT of the chest).
- **Study** – one hospital visit; it can contain several scans.
- **Segmentation / outline** – a drawing that marks an organ or tumour on the images.
- **DICOM** – the standard file format for medical images. Open with free viewers such as
  3D Slicer, Horos (Mac), RadiAnt or Weasis.

### Something wrong?
- *No results* → remove one of your choices.
- *Download stopped* → press *Start download* again; it resumes.
- Data and questions: https://learn.canceridc.dev · forum: https://discourse.canceridc.dev
""")


# ---------------------------------------------------------------- ask (global chat)
download_plan = {
    "what": (f"a sample of {int(n_pat)} patients" if how_much.startswith("A small")
             else "everything in this selection"),
    "scans": len(uids),
    "size_gb": float(size_gb),
    "folder": folder,
    "layout": layout_name.replace("collection", "dataset"),
    "source": source,
}
download_plan.update(
    lines=download_lines(download_plan, human_size),
    local=(f"The download plan is {download_plan['what']}: "
           f"{len(uids):,} scans, {human_size(float(size_gb))}."),
    recipe=recipe, uids=uids, existing=existing, layout_name=layout_name, free_gb=free_gb,
)
licence_names = ", ".join(lic["value"].dropna().astype(str).head(4).tolist())
render_chat(
    selection_lines(recipe, summary, human_size),
    f"Your filters match {summary['patients']:,} patients, "
    f"{summary['series']:,} scans, {summary['collections']:,} datasets, "
    f"{human_size(summary['size_GB'])}. "
    f"Licences in this selection include {licence_names or 'unknown'}.",
    download_plan,
)
