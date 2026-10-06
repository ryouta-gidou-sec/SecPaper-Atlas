"""Streamlit user interface for SecPaper Atlas."""

from __future__ import annotations

import altair as alt
import streamlit as st

from src.classifier import ClassificationError, create_classifier
from src.config import configure_logging, get_settings
from src.database import Database, FolderError, FOLDER_NAME_MAX_LENGTH, NOTE_MAX_LENGTH
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


def save_list_user_state(editor_key: str, paper_ids: list[int], columns: dict[str, str]) -> None:
    """Persist the current editor event before Streamlit reloads the filtered list."""
    edits = st.session_state[editor_key].get("edited_rows", {})
    for row_index, edited in edits.items():
        values = {columns[column]: value for column, value in edited.items() if column in columns}
        if values:
            database.set_user_state(paper_ids[int(row_index)], **values)
    # Fresh DB values become the next editor's baseline (including changed filters).
    st.session_state["user_state_revision"] = st.session_state.get("user_state_revision", 0) + 1


def save_detail_user_state(paper_id: int, flag: str, widget_key: str) -> None:
    database.set_user_state(paper_id, **{flag: st.session_state[widget_key]})
    st.session_state["user_state_revision"] = st.session_state.get("user_state_revision", 0) + 1


database, settings, logger = application_services()


def organization_saved(message: str) -> None:
    st.session_state["_folder_notice"] = message
    st.rerun()

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
    st.header("📁 " + t("Folders", language))
    if notice := st.session_state.pop("_folder_notice", None):
        st.success(t(notice, language))
    folders = database.list_folders()
    folder_names = {folder["id"]: folder["name"] for folder in folders}
    with st.expander("＋ " + t("New Folder", language), expanded=not folders):
        with st.form("new_folder", clear_on_submit=True):
            new_folder_name = st.text_input(
                t("Folder name", language), max_chars=FOLDER_NAME_MAX_LENGTH,
                key="new_folder_name",
            )
            create_folder = st.form_submit_button(t("Create", language), key="create_folder")
        if create_folder:
            try:
                database.create_folder(new_folder_name)
            except FolderError as exc:
                st.error(t(str(exc), language))
            else:
                organization_saved("Folder created.")

    if st.session_state.get("filter_folder") not in folder_names:
        st.session_state["filter_folder"] = None
    selected_folder_id = st.radio(
        t("Open folder", language), [None, *folder_names], key="filter_folder",
        format_func=lambda value: "📁 " + (
            t("All Papers", language) if value is None else folder_names[value]
        ),
    )
    if folders:
        with st.expander(t("Manage folders", language)):
            if st.session_state.get("manage_folder_id") not in folder_names:
                st.session_state["manage_folder_id"] = folders[0]["id"]
            managed_id = st.selectbox(
                t("Folder", language), list(folder_names), format_func=folder_names.__getitem__,
                key="manage_folder_id",
            )
            # Include the current name to refresh the input after a successful rename.
            with st.form(f"rename-folder-{managed_id}-{folder_names[managed_id]}"):
                renamed = st.text_input(
                    t("Folder name", language), value=folder_names[managed_id],
                    max_chars=FOLDER_NAME_MAX_LENGTH,
                    key=f"rename-folder-{managed_id}-{folder_names[managed_id]}",
                )
                rename_folder = st.form_submit_button(t("Rename Folder", language), key="rename_folder")
            if rename_folder:
                try:
                    database.rename_folder(managed_id, renamed)
                except FolderError as exc:
                    st.error(t(str(exc), language))
                else:
                    organization_saved("Folder renamed.")
            with st.form(f"delete-folder-{managed_id}-{folder_names[managed_id]}"):
                st.warning(t("Only the folder and its memberships will be removed. Papers and their saved data are kept.", language))
                confirm_delete = st.checkbox(
                    t('Delete folder "{name}"', language, name=folder_names[managed_id]),
                    key=f"confirm-delete-folder-{managed_id}-{folder_names[managed_id]}",
                )
                delete_folder = st.form_submit_button(t("Delete Folder", language), key="delete_folder")
            if delete_folder:
                if not confirm_delete:
                    st.error(t("Confirm the folder name before deleting.", language))
                else:
                    try:
                        database.delete_folder(managed_id)
                    except FolderError as exc:
                        st.error(t(str(exc), language))
                    else:
                        organization_saved("Folder deleted. Papers were kept.")

    st.divider()
    st.header(t("Search & filters", language))
    keyword = st.text_input(
        t("Keyword", language), placeholder=t("Title, abstract, tag, vulnerability", language),
        key="filter_keyword",
    )
    favorites_only = st.checkbox(t("Favorites only", language), key="filter_favorites")
    read_later_only = st.checkbox(t("Read Later only", language), key="filter_read_later")
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

    st.header(t("Classifier", language))
    st.caption(f"{t('Provider', language)}: {settings.classifier_provider}")
    st.caption(f"{t('Model', language)}: {settings.classifier_model or t('Not configured', language)}")
    st.caption(t("Local processing on this PC" if settings.classifier_provider == "local"
                 else "Extracted classification input is sent to OpenAI", language))


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
        category_chart = alt.Chart(alt.Data(values=category_rows)).mark_bar().encode(
            x=alt.X(
                field=t("Papers", language), type="quantitative",
                scale=alt.Scale(domainMin=0, zero=True),
                axis=alt.Axis(format="d", tickMinStep=1),
            ),
            y=alt.Y(field=t("Category", language), type="nominal"),
        )
        st.altair_chart(category_chart, width="stretch")
    else:
        st.info(t("Add PDFs to papers/inbox and run a scan to build the dashboard.", language))

papers = database.search_papers(
    folder_id=selected_folder_id,
    keyword=keyword,
    categories=categories,
    tags=selected_tags,
    methods=selected_methods,
    vulnerabilities=selected_vulnerabilities,
    relevances=relevances,
    statuses=statuses,
    classification_statuses=classification_statuses,
    favorites_only=favorites_only,
    read_later_only=read_later_only,
    year_min=year_min,
    year_max=year_max,
)

st.subheader(t("Papers", language))
if selected_folder_id is not None:
    st.text("📁 " + folder_names[selected_folder_id])
st.caption(t("{count} result(s)", language, count=len(papers)))
if papers:
    table_rows = [
        {
            t("ID", language): paper["id"],
            t("Title", language): paper["title"] or paper["filename"],
            t("Favorite", language): paper["user_state"]["is_favorite"],
            t("Read Later", language): paper["user_state"]["read_later"],
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
            t("Folders", language): ", ".join(folder["name"] for folder in paper["folders"]),
        }
        for paper in papers
    ]
    state_columns = {t("Favorite", language): "is_favorite", t("Read Later", language): "read_later"}
    editor_key = f"paper-user-state-{language}-{st.session_state.get('user_state_revision', 0)}"
    st.data_editor(
        table_rows, hide_index=True, width="stretch", key=editor_key,
        disabled=[column for column in table_rows[0] if column not in state_columns],
        column_config={
            t("Favorite", language): st.column_config.CheckboxColumn("★ " + t("Favorite", language)),
            t("Read Later", language): st.column_config.CheckboxColumn("🔖 " + t("Read Later", language)),
        },
        on_change=save_list_user_state,
        args=(editor_key, [paper["id"] for paper in papers], state_columns),
    )

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
    state_controls = st.columns([1, 1, 4])
    for column, flag, label in (
        (state_controls[0], "is_favorite", "Favorite"),
        (state_controls[1], "read_later", "Read Later"),
    ):
        widget_key = f"user-state-{selected_paper['id']}-{flag}"
        st.session_state[widget_key] = selected_paper["user_state"][flag]
        with column:
            st.toggle(t(label, language), key=widget_key, on_change=save_detail_user_state,
                      args=(selected_paper["id"], flag, widget_key))
    detail_left, detail_right = st.columns([2, 1])
    with detail_left:
        st.markdown("#### 📁 " + t("Folders", language))
        if folders:
            membership_key = f"paper-folders-{selected_paper['id']}"
            if membership_key in st.session_state:
                previous = st.session_state[membership_key]
                valid = [value for value in previous if value in folder_names]
                if valid != previous:
                    st.session_state[membership_key] = valid
            with st.form(f"paper-folders-form-{selected_paper['id']}"):
                paper_folder_ids = st.multiselect(
                    t("Folders", language), list(folder_names),
                    default=[folder["id"] for folder in selected_paper["folders"]],
                    format_func=folder_names.__getitem__, key=membership_key,
                    placeholder=t("Choose folders", language),
                )
                save_folders = st.form_submit_button(t("Save folders", language), key="save_paper_folders")
            if save_folders:
                try:
                    database.set_paper_folders(selected_paper["id"], paper_folder_ids)
                except FolderError as exc:
                    st.error(t(str(exc), language))
                else:
                    organization_saved("Folders saved.")
        else:
            st.info(t("Create a folder in the sidebar to organize this paper.", language))
        st.markdown("#### 📝 " + t("Notes", language))
        with st.form(f"paper-note-form-{selected_paper['id']}"):
            note_text = st.text_area(
                t("Notes", language), value=selected_paper["note"],
                max_chars=NOTE_MAX_LENGTH, key=f"paper-note-{selected_paper['id']}",
                placeholder=t("Write your reading notes here", language),
            )
            save_note = st.form_submit_button(t("Save note", language), key="save_paper_note")
        if save_note:
            try:
                database.set_note(selected_paper["id"], note_text)
            except ValueError as exc:
                st.error(t(str(exc), language))
            else:
                organization_saved("Note saved.")
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
