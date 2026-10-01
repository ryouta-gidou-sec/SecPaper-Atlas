"""Streamlit user interface for Research Paper Classifier v0.1."""

from __future__ import annotations

import streamlit as st

from src.classifier import ClassificationError, PaperClassifier
from src.config import configure_logging, get_settings
from src.database import Database
from src.models import ClassificationStatus, PaperStatus, PrimaryCategory, Relevance, enum_values
from src.scanner import scan_inbox


st.set_page_config(
    page_title="Research Paper Classifier",
    page_icon="📚",
    layout="wide",
)

st.markdown(
    """
    <style>
      .block-container {padding-top: 2rem; max-width: 1500px;}
      [data-testid="stMetric"] {background: #f7f9fc; border: 1px solid #e3e8ef;
        border-radius: 12px; padding: 14px;}
      .rpc-muted {color: #64748b; font-size: .92rem;}
      .rpc-pill {display: inline-block; padding: .18rem .55rem; margin: .1rem;
        border-radius: 999px; background: #e8eefc; color: #263b73; font-size: .82rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def application_services() -> tuple[Database, object, object]:
    settings = get_settings()
    settings.ensure_directories()
    database = Database(settings.database_path)
    database.initialize()
    logger = configure_logging(settings.logs_dir)
    return database, settings, logger


database, settings, logger = application_services()

st.title("Research Paper Classifier")
st.caption(
    "A local-first workspace for triaging authentication and authorization security research."
)

with st.sidebar:
    st.header("Library")
    if st.button("Scan papers/inbox", type="primary", width="stretch"):
        classifier = None
        if settings.openai_api_key:
            try:
                classifier = PaperClassifier(
                    api_key=settings.openai_api_key,
                    model=settings.openai_model,
                )
            except ClassificationError as exc:
                st.error(str(exc))
        with st.spinner("Scanning new PDFs…"):
            scan_results = scan_inbox(
                inbox_dir=settings.inbox_dir,
                database=database,
                classifier=classifier,
                logger=logger,
            )
        if not scan_results:
            st.info("No valid PDFs found in papers/inbox.")
        else:
            st.session_state["scan_results"] = [item.to_dict() for item in scan_results]

    if "scan_results" in st.session_state:
        with st.expander("Last scan results", expanded=True):
            for result in st.session_state["scan_results"]:
                icon = {"Classified": "✅", "Skipped": "↪️", "Failed": "❌"}.get(
                    str(result["status"]), "⚠️"
                )
                st.write(f"{icon} **{result['filename']}** — {result['status']}")
                st.caption(str(result["message"]))

    st.divider()
    st.header("Search & filters")
    keyword = st.text_input("Keyword", placeholder="Title, abstract, tag, vulnerability")
    facets = database.list_facets()
    categories = st.multiselect("Primary category", enum_values(PrimaryCategory))
    selected_tags = st.multiselect("Tags", facets["tags"])
    selected_methods = st.multiselect("Research methods", facets["research_methods"])
    selected_vulnerabilities = st.multiselect(
        "Target vulnerabilities", facets["target_vulnerabilities"]
    )
    relevances = st.multiselect("Relevance", enum_values(Relevance))
    statuses = st.multiselect("Status", enum_values(PaperStatus))
    classification_statuses = st.multiselect(
        "Classification status", enum_values(ClassificationStatus)
    )

    all_papers_for_years = database.search_papers()
    known_years = [paper["year"] for paper in all_papers_for_years if paper["year"]]
    year_min: int | None = None
    year_max: int | None = None
    if known_years:
        lower, upper = min(known_years), max(known_years)
        if lower < upper:
            selected_range = st.slider("Publication year", lower, upper, (lower, upper))
            year_min, year_max = selected_range
        else:
            st.caption(f"Publication year: {lower}")


dashboard = database.dashboard_counts()
metric_columns = st.columns(5)
metric_columns[0].metric("Papers", dashboard["total"])
metric_columns[1].metric("Relevance A", dashboard["relevances"].get("A", 0))
metric_columns[2].metric("Relevance B", dashboard["relevances"].get("B", 0))
metric_columns[3].metric("Relevance C", dashboard["relevances"].get("C", 0))
metric_columns[4].metric("Unread", dashboard["unread"])

with st.expander("Category overview", expanded=dashboard["total"] > 0):
    category_rows = [
        {"Category": label, "Papers": count}
        for label, count in dashboard["categories"].items()
    ]
    if category_rows:
        st.bar_chart(category_rows, x="Category", y="Papers", horizontal=True)
    else:
        st.info("Add PDFs to papers/inbox and run a scan to build the dashboard.")

papers = database.search_papers(
    keyword=keyword,
    categories=categories,
    tags=selected_tags,
    methods=selected_methods,
    vulnerabilities=selected_vulnerabilities,
    relevances=relevances,
    statuses=statuses,
    classification_statuses=classification_statuses,
    year_min=year_min,
    year_max=year_max,
)

st.subheader("Papers")
st.caption(f"{len(papers)} result(s)")
if papers:
    table_rows = [
        {
            "ID": paper["id"],
            "Title": paper["title"] or paper["filename"],
            "Year": paper["year"],
            "Primary Category": paper["primary_category"] or "Unclassified",
            "Classification": paper["classification_status"],
            "Tags": ", ".join(paper["tags"]),
            "Research Methods": ", ".join(paper["research_methods"]),
            "Relevance": paper["relevance"] or "—",
            "Status": paper["status"],
        }
        for paper in papers
    ]
    st.dataframe(table_rows, hide_index=True, width="stretch")

    options = {f"#{paper['id']} · {paper['title'] or paper['filename']}": paper["id"] for paper in papers}
    selected_label = st.selectbox("Open paper details", list(options))
    selected_paper = database.get_paper(options[selected_label])
else:
    selected_paper = None
    st.info("No papers match the current filters.")

if selected_paper:
    st.divider()
    st.subheader(selected_paper["title"] or selected_paper["filename"])
    detail_left, detail_right = st.columns([2, 1])
    with detail_left:
        st.markdown(f"**Authors:** {', '.join(selected_paper['authors']) or 'Unknown'}")
        st.markdown(f"**Year:** {selected_paper['year'] or 'Unknown'}")
        st.markdown(f"**Venue:** {selected_paper['venue'] or 'Unknown'}")
        st.markdown("**Abstract**")
        st.write(selected_paper["abstract"] or "No abstract could be extracted.")
        st.markdown(f"**Keywords:** {', '.join(selected_paper['keywords']) or 'None extracted'}")
        st.markdown(f"**Classification status:** {selected_paper['classification_status']}")
        if selected_paper["metadata_review_reasons"]:
            for reason in selected_paper["metadata_review_reasons"]:
                st.warning(reason)
        if not selected_paper["abstract"] and selected_paper["introduction_excerpt"]:
            st.markdown("**Introduction excerpt (abstract fallback)**")
            st.write(selected_paper["introduction_excerpt"])
        with st.expander("Extraction sources"):
            st.json(selected_paper["metadata_sources"])
        st.markdown(
            f"**Research methods:** {', '.join(selected_paper['research_methods']) or 'None'}"
        )
        st.markdown(
            "**Target vulnerabilities:** "
            + (", ".join(selected_paper["target_vulnerabilities"]) or "None")
        )
        st.markdown(f"**Relevance reason:** {selected_paper['relevance_reason'] or 'Unavailable'}")
        st.markdown(
            f"**Confidence:** {selected_paper['relevance_confidence'] if selected_paper['relevance_confidence'] is not None else 'Unknown'}"
        )
        st.code(selected_paper["filepath"], language=None)
        if selected_paper["classification_error"]:
            st.warning(f"AI classification unavailable: {selected_paper['classification_error']}")

    with detail_right:
        st.markdown("#### Human correction")
        category_options = enum_values(PrimaryCategory)
        relevance_options = enum_values(Relevance)
        status_options = enum_values(PaperStatus)
        with st.form(f"review-{selected_paper['id']}"):
            selected_category = st.selectbox(
                "Primary category",
                category_options,
                index=category_options.index(selected_paper["primary_category"])
                if selected_paper["primary_category"] in category_options
                else category_options.index(PrimaryCategory.OTHER_SECURITY.value),
            )
            tags_text = st.text_area(
                "Tags (comma-separated; custom tags allowed)",
                value=", ".join(selected_paper["tags"]),
            )
            methods_text = st.text_area(
                "Research methods (comma-separated)",
                value=", ".join(selected_paper["research_methods"]),
            )
            vulnerabilities_text = st.text_area(
                "Target vulnerabilities (comma-separated)",
                value=", ".join(selected_paper["target_vulnerabilities"]),
            )
            selected_relevance = st.selectbox(
                "Relevance",
                relevance_options,
                index=relevance_options.index(selected_paper["relevance"])
                if selected_paper["relevance"] in relevance_options
                else 1,
            )
            relevance_reason = st.text_area(
                "Relevance reason",
                value=selected_paper["relevance_reason"] or "",
                max_chars=500,
            )
            selected_status = st.selectbox(
                "Status",
                status_options,
                index=status_options.index(selected_paper["status"]),
            )
            submitted = st.form_submit_button("Save review", type="primary")
        if submitted:
            edited_tags = [item.strip() for item in tags_text.split(",") if item.strip()]
            edited_methods = [item.strip() for item in methods_text.split(",") if item.strip()]
            edited_vulnerabilities = [
                item.strip() for item in vulnerabilities_text.split(",") if item.strip()
            ]
            database.update_review(
                selected_paper["id"],
                primary_category=selected_category,
                tags=edited_tags,
                relevance=selected_relevance,
                status=selected_status,
                research_methods=edited_methods,
                target_vulnerabilities=edited_vulnerabilities,
                relevance_reason=relevance_reason,
            )
            st.success("Review saved. The original AI values were preserved.")
            st.rerun()

        with st.expander("Original AI result"):
            st.write(f"Category: {selected_paper['ai_primary_category'] or 'Unavailable'}")
            st.write(f"Tags: {', '.join(selected_paper['ai_tags']) or 'Unavailable'}")
            st.write(
                "Methods: "
                + (", ".join(selected_paper["ai_research_methods"]) or "Unavailable")
            )
            st.write(
                "Vulnerabilities: "
                + (", ".join(selected_paper["ai_target_vulnerabilities"]) or "Unavailable")
            )
            st.write(f"Relevance: {selected_paper['ai_relevance'] or 'Unavailable'}")
            st.write(f"Reason: {selected_paper['ai_relevance_reason'] or 'Unavailable'}")
            st.write(f"Manually reviewed: {'Yes' if selected_paper['manually_reviewed'] else 'No'}")

st.divider()
st.caption(
    "Local-first: source PDFs are never moved, renamed, edited, uploaded in full, or committed by default."
)
