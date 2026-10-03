"""Streamlit user interface for SecPaper Atlas."""

from __future__ import annotations

import streamlit as st

from src.classifier import ClassificationError, create_classifier
from src.config import configure_logging, get_settings
from src.database import Database
from src.i18n import LANGUAGES, display_enum, t
from src.models import ClassificationStatus, PaperStatus, PrimaryCategory, Relevance, enum_values
from src.pdf_access import PDFAccessError, open_paper_pdf
from src.scanner import scan_inbox


st.set_page_config(
    page_title="SecPaper Atlas",
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

with st.sidebar:
    language = st.selectbox(
        "Language / 言語 / 언어", list(LANGUAGES),
        format_func=LANGUAGES.__getitem__, key="ui_language",
    )

# Keyed widgets retain their canonical values, but the browser can retain old
# formatted labels. Re-publish those values once when the display language changes.
language_changed = language != st.session_state.get("_ui_last_language", language)
if language_changed:
    enum_filter_keys = {"filter_categories", "filter_statuses", "filter_classification_statuses"}
    for widget_key in list(st.session_state):
        if widget_key in enum_filter_keys or (
            widget_key.startswith("review-")
            and widget_key.endswith(("-category", "-relevance", "-status"))
        ):
            st.session_state[widget_key] = st.session_state[widget_key]
st.session_state["_ui_last_language"] = language

st.title("SecPaper Atlas")
st.caption(t("header_caption", language))

with st.sidebar:
    st.header(t("Classifier", language))
    st.caption(f"{t('Provider', language)}: {settings.classifier_provider}")
    st.caption(f"{t('Model', language)}: {settings.classifier_model or t('Not configured', language)}")
    st.caption(t("Local processing on this PC" if settings.classifier_provider == "local"
                 else "Extracted classification input is sent to OpenAI", language))
    st.header(t("Library", language))
    if st.button(t("Scan papers/inbox", language), type="primary", width="stretch", key="scan_inbox"):
        classifier = None
        try:
            classifier = create_classifier(settings)
        except ClassificationError as exc:
            st.error(str(exc))
        with st.spinner(t("Scanning new PDFs…", language)):
            try:
                scan_results = scan_inbox(
                    inbox_dir=settings.inbox_dir,
                    database=database,
                    classifier=classifier,
                    logger=logger,
                )
            finally:
                if classifier is not None:
                    classifier.close()
        if not scan_results:
            st.info(t("No valid PDFs found in papers/inbox.", language))
        else:
            st.session_state["scan_results"] = [item.to_dict() for item in scan_results]

    if "scan_results" in st.session_state:
        with st.expander(t("Last scan results", language), expanded=True):
            for result in st.session_state["scan_results"]:
                icon = {"Classified": "✅", "Skipped": "↪️", "Failed": "❌"}.get(
                    str(result["status"]), "⚠️"
                )
                st.write(f"{icon} **{result['filename']}** — {t(str(result['status']), language)}")
                st.caption(t(str(result["message"]), language))

    st.divider()
    st.header(t("Search & filters", language))
    keyword = st.text_input(
        t("Keyword", language), placeholder=t("Title, abstract, tag, vulnerability", language),
        key="filter_keyword",
    )
    facets = database.list_facets()
    categories = st.multiselect(
        t("Primary category", language), enum_values(PrimaryCategory),
        format_func=lambda value: display_enum(value, language), key="filter_categories",
        placeholder=t("Choose options", language),
    )
    selected_tags = st.multiselect(
        t("Tags", language), facets["tags"], key="filter_tags",
        placeholder=t("Choose options", language),
    )
    selected_methods = st.multiselect(
        t("Research methods", language), facets["research_methods"], key="filter_methods",
        placeholder=t("Choose options", language),
    )
    selected_vulnerabilities = st.multiselect(
        t("Target vulnerabilities", language), facets["target_vulnerabilities"],
        key="filter_vulnerabilities",
        placeholder=t("Choose options", language),
    )
    relevances = st.multiselect(
        t("Relevance", language), enum_values(Relevance), key="filter_relevances",
        placeholder=t("Choose options", language),
    )
    statuses = st.multiselect(
        t("Status", language), enum_values(PaperStatus),
        format_func=lambda value: display_enum(value, language), key="filter_statuses",
        placeholder=t("Choose options", language),
    )
    classification_statuses = st.multiselect(
        t("Classification status", language), enum_values(ClassificationStatus),
        format_func=lambda value: display_enum(value, language), key="filter_classification_statuses",
        placeholder=t("Choose options", language),
    )

    all_papers_for_years = database.search_papers()
    known_years = [paper["year"] for paper in all_papers_for_years if paper["year"]]
    year_min: int | None = None
    year_max: int | None = None
    if known_years:
        lower, upper = min(known_years), max(known_years)
        if lower < upper:
            selected_range = st.slider(
                t("Publication year", language), lower, upper, (lower, upper), key="filter_years",
            )
            if selected_range != (lower, upper):
                year_min, year_max = selected_range
        else:
            st.caption(f"{t('Publication year', language)}: {lower}")


dashboard = database.dashboard_counts()
metric_columns = st.columns(5)
metric_columns[0].metric(t("Papers", language), dashboard["total"])
metric_columns[1].metric(t("Relevance A", language), dashboard["relevances"].get("A", 0))
metric_columns[2].metric(t("Relevance B", language), dashboard["relevances"].get("B", 0))
metric_columns[3].metric(t("Relevance C", language), dashboard["relevances"].get("C", 0))
metric_columns[4].metric(t("Unread", language), dashboard["unread"])

with st.expander(t("Category overview", language), expanded=dashboard["total"] > 0):
    category_rows = [
        {t("Category", language): display_enum(label, language), t("Papers", language): count}
        for label, count in dashboard["categories"].items()
    ]
    if category_rows:
        st.bar_chart(category_rows, x=t("Category", language), y=t("Papers", language), horizontal=True)
    else:
        st.info(t("Add PDFs to papers/inbox and run a scan to build the dashboard.", language))

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

st.subheader(t("Papers", language))
st.caption(t("{count} result(s)", language, count=len(papers)))
if papers:
    table_rows = [
        {
            t("ID", language): paper["id"],
            t("Title", language): paper["title"] or paper["filename"],
            t("Year", language): paper["year"],
            t("Primary Category", language): display_enum(paper["effective_primary_category"], language)
            if paper["effective_primary_category"] else t("Unclassified", language),
            t("Classification source", language): t("Human reviewed", language)
            if paper["manually_reviewed"]
            else (
                t("AI, not reviewed", language)
                if paper["ai_primary_category"]
                else t("No AI result", language)
            ),
            t("Classification", language): display_enum(paper["classification_status"], language),
            t("AI Provider", language): paper["classification_provider"] or "—",
            t("AI Model", language): paper["classification_model"] or "—",
            t("Tags", language): ", ".join(paper["effective_tags"]),
            t("Research Methods", language): ", ".join(paper["effective_research_methods"]),
            t("Relevance", language): paper["effective_relevance"] or "—",
            t("Status", language): display_enum(paper["status"], language),
        }
        for paper in papers
    ]
    st.dataframe(table_rows, hide_index=True, width="stretch")

    options = {paper["id"]: f"#{paper['id']} · {paper['title'] or paper['filename']}" for paper in papers}
    selected_id = st.selectbox(
        t("Open paper details", language), list(options),
        format_func=options.__getitem__, key="selected_paper_id",
    )
    selected_paper = database.get_paper(selected_id)
else:
    selected_paper = None
    st.info(t("No papers match the current filters.", language))

if selected_paper:
    st.divider()
    st.subheader(selected_paper["title"] or selected_paper["filename"])
    detail_left, detail_right = st.columns([2, 1])
    with detail_left:
        st.markdown(f"**{t('Authors', language)}:** {', '.join(selected_paper['authors']) or t('Unknown', language)}")
        st.markdown(f"**{t('Year', language)}:** {selected_paper['year'] or t('Unknown', language)}")
        st.markdown(f"**{t('Venue', language)}:** {selected_paper['venue'] or t('Unknown', language)}")
        if st.button(
            "📄 " + t("Open PDF in default browser", language), key="open_paper_pdf",
        ):
            try:
                open_paper_pdf(settings.inbox_dir, selected_paper)
            except PDFAccessError as exc:
                st.warning(t(str(exc), language))
        st.markdown(f"**{t('Abstract', language)}**")
        st.write(selected_paper["abstract"] or t("No abstract could be extracted.", language))
        st.markdown(f"**{t('Keywords', language)}:** {', '.join(selected_paper['keywords']) or t('None extracted', language)}")
        st.markdown(f"**{t('Classification status', language)}:** {display_enum(selected_paper['classification_status'], language)}")
        st.caption(
            f"{t('AI Provider', language)}: {selected_paper['classification_provider'] or t('Unknown', language)} · "
            f"{t('Model', language)}: {selected_paper['classification_model'] or t('Unknown', language)} · "
            f"{t('Classified at', language)}: {selected_paper['classified_at'] or t('Unknown', language)}"
        )
        with st.expander(t("AI classification history", language)):
            for run in database.classification_history(selected_paper["id"]):
                st.caption(f"#{run['id']} · {run['provider'] or t('Unknown', language)} · "
                           f"{run['model'] or t('Unknown', language)} · {display_enum(run['status'], language)}")
                if run["result"]:
                    st.json(run["result"])
                elif run["error"]:
                    st.write(run["error"])
        if selected_paper["metadata_review_reasons"]:
            for reason in selected_paper["metadata_review_reasons"]:
                st.warning(t(reason, language))
        if not selected_paper["abstract"] and selected_paper["introduction_excerpt"]:
            st.markdown(f"**{t('Introduction excerpt (abstract fallback)', language)}**")
            st.write(selected_paper["introduction_excerpt"])
        with st.expander(t("Extraction sources", language)):
            st.json(selected_paper["metadata_sources"])
        if selected_paper["manually_reviewed"]:
            classification_heading = "Classification — Human reviewed"
        elif selected_paper["ai_primary_category"]:
            classification_heading = "Classification — AI proposal, not reviewed"
        else:
            classification_heading = "Classification — unavailable"
        st.markdown(f"#### {t(classification_heading, language)}")
        st.markdown(
            f"**{t('Primary category', language)}:** "
            + (display_enum(selected_paper['effective_primary_category'], language)
               if selected_paper['effective_primary_category'] else t('Unavailable', language))
        )
        st.markdown(f"**{t('Tags', language)}:** {', '.join(selected_paper['effective_tags']) or t('None', language)}")
        st.markdown(
            f"**{t('Research methods', language)}:** {', '.join(selected_paper['effective_research_methods']) or t('None', language)}"
        )
        st.markdown(
            f"**{t('Target vulnerabilities', language)}:** "
            + (", ".join(selected_paper["effective_target_vulnerabilities"]) or t("None", language))
        )
        st.markdown(f"**{t('Relevance', language)}:** {selected_paper['effective_relevance'] or t('Unavailable', language)}")
        st.markdown(
            f"**{t('Relevance reason', language)}:** {selected_paper['effective_relevance_reason'] or t('Unavailable', language)}"
        )
        st.markdown(
            f"**{t('Confidence', language)}:** {selected_paper['effective_relevance_confidence'] if selected_paper['effective_relevance_confidence'] is not None else t('Unknown', language)}"
        )
        if selected_paper["classification_error"]:
            st.warning(t("AI classification unavailable: {error}", language,
                         error=t(selected_paper['classification_error'], language)))

    with detail_right:
        st.markdown(f"#### {t('Human correction', language)}")
        category_options = [None, *enum_values(PrimaryCategory)]
        relevance_options = [None, *enum_values(Relevance)]
        status_options = enum_values(PaperStatus)
        with st.form(f"review-{selected_paper['id']}"):
            selected_category = st.selectbox(
                t("Primary category", language),
                category_options,
                index=0
                if language_changed and f"review-{selected_paper['id']}-category" in st.session_state
                else category_options.index(selected_paper["primary_category"])
                if selected_paper["manually_reviewed"]
                and selected_paper["primary_category"] in category_options
                else 0,
                format_func=lambda value: display_enum(value, language)
                if value else t("Select a category", language),
                key=f"review-{selected_paper['id']}-category",
                placeholder=t("Select a category", language),
            )
            tags_text = st.text_area(
                t("Tags (comma-separated; custom tags allowed)", language),
                value=", ".join(selected_paper["tags"])
                if selected_paper["manually_reviewed"]
                else "",
                key=f"review-{selected_paper['id']}-tags",
            )
            methods_text = st.text_area(
                t("Research methods (comma-separated)", language),
                value=", ".join(selected_paper["research_methods"])
                if selected_paper["manually_reviewed"]
                else "",
                key=f"review-{selected_paper['id']}-methods",
            )
            vulnerabilities_text = st.text_area(
                t("Target vulnerabilities (comma-separated)", language),
                value=", ".join(selected_paper["target_vulnerabilities"])
                if selected_paper["manually_reviewed"]
                else "",
                key=f"review-{selected_paper['id']}-vulnerabilities",
            )
            selected_relevance = st.selectbox(
                t("Relevance", language),
                relevance_options,
                index=0
                if language_changed and f"review-{selected_paper['id']}-relevance" in st.session_state
                else relevance_options.index(selected_paper["relevance"])
                if selected_paper["manually_reviewed"]
                and selected_paper["relevance"] in relevance_options
                else 0,
                format_func=lambda value: value or t("Select relevance", language),
                key=f"review-{selected_paper['id']}-relevance",
                placeholder=t("Select relevance", language),
            )
            relevance_reason = st.text_area(
                t("Relevance reason", language),
                value=(selected_paper["relevance_reason"] or "")
                if selected_paper["manually_reviewed"]
                else "",
                max_chars=500,
                key=f"review-{selected_paper['id']}-reason",
            )
            selected_status = st.selectbox(
                t("Status", language),
                status_options,
                index=0
                if language_changed and f"review-{selected_paper['id']}-status" in st.session_state
                else status_options.index(selected_paper["status"]),
                format_func=lambda value: display_enum(value, language),
                key=f"review-{selected_paper['id']}-status",
            )
            submitted = st.form_submit_button(
                t("Save review", language), type="primary", key=f"review-{selected_paper['id']}-save",
            )
        if submitted:
            if selected_category is None or selected_relevance is None:
                st.error(t("Select a primary category and relevance before saving the review.", language))
            else:
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
                st.success(t("Review saved. The original AI values were preserved.", language))
                st.rerun()

        with st.expander(t("Latest AI result (earlier originals in history)", language)):
            st.write(f"{t('Category', language)}: "
                     + (display_enum(selected_paper['ai_primary_category'], language)
                        if selected_paper['ai_primary_category'] else t('Unavailable', language)))
            st.write(f"{t('Tags', language)}: {', '.join(selected_paper['ai_tags']) or t('Unavailable', language)}")
            st.write(
                f"{t('Methods', language)}: "
                + (", ".join(selected_paper["ai_research_methods"]) or t("Unavailable", language))
            )
            st.write(
                f"{t('Vulnerabilities', language)}: "
                + (", ".join(selected_paper["ai_target_vulnerabilities"]) or t("Unavailable", language))
            )
            st.write(f"{t('Relevance', language)}: {selected_paper['ai_relevance'] or t('Unavailable', language)}")
            st.write(f"{t('Reason', language)}: {selected_paper['ai_relevance_reason'] or t('Unavailable', language)}")
            st.write(f"{t('Manually reviewed', language)}: {t('Yes' if selected_paper['manually_reviewed'] else 'No', language)}")

st.divider()
st.caption(t("footer_caption", language))
