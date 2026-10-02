"""Presentation-only translations; stored and classifier values stay canonical."""

from __future__ import annotations

from enum import Enum


LANGUAGES = {"ja": "日本語", "en": "English", "ko": "한국어"}

# Rows are (English, Japanese, Korean). No paper text or provider output belongs here.
_MESSAGES = {
    "header_caption": (
        "A local-first workspace for organizing and classifying security research papers.",
        "セキュリティ研究論文を整理・分類するローカルファーストの研究支援ツール。",
        "보안 연구 논문을 정리하고 분류하기 위한 로컬 우선 연구 지원 도구.",
    ),
    "Classifier": ("Classifier", "分類設定", "분류 설정"),
    "Provider": ("Provider", "プロバイダー", "제공자"),
    "Model": ("Model", "モデル", "모델"),
    "Not configured": ("Not configured", "未設定", "설정되지 않음"),
    "Local processing on this PC": ("Local processing on this PC", "このPCでローカル処理", "이 PC에서 로컬 처리"),
    "Extracted classification input is sent to OpenAI": (
        "Extracted classification input is sent to OpenAI",
        "抽出した分類用データをOpenAIに送信",
        "추출한 분류용 데이터를 OpenAI로 전송",
    ),
    "Library": ("Library", "ライブラリ", "라이브러리"),
    "Scan papers/inbox": ("Scan papers/inbox", "papers/inboxをスキャン", "papers/inbox 스캔"),
    "Last scan results": ("Last scan results", "前回のスキャン結果", "최근 스캔 결과"),
    "Search & filters": ("Search & filters", "検索・絞り込み", "검색 및 필터"),
    "Keyword": ("Keyword", "キーワード", "검색어"),
    "Choose options": ("Choose options", "選択してください", "선택하세요"),
    "Title, abstract, tag, vulnerability": (
        "Title, abstract, tag, vulnerability", "タイトル、要旨、タグ、脆弱性", "제목, 초록, 태그, 취약점",
    ),
    "Primary category": ("Primary category", "主分類", "주 분류"),
    "Tags": ("Tags", "タグ", "태그"),
    "Research methods": ("Research methods", "研究手法", "연구 방법"),
    "Target vulnerabilities": ("Target vulnerabilities", "対象脆弱性", "대상 취약점"),
    "Relevance": ("Relevance", "関連度", "관련도"),
    "Status": ("Status", "読書状況", "읽기 상태"),
    "Classification status": ("Classification status", "分類状況", "분류 상태"),
    "Publication year": ("Publication year", "発表年", "발행 연도"),
    "Papers": ("Papers", "論文", "논문"),
    "Relevance A": ("Relevance A", "関連度 A", "관련도 A"),
    "Relevance B": ("Relevance B", "関連度 B", "관련도 B"),
    "Relevance C": ("Relevance C", "関連度 C", "관련도 C"),
    "Unread": ("Unread", "未読", "읽지 않음"),
    "Category overview": ("Category overview", "分類別の論文数", "분류별 논문 수"),
    "Category": ("Category", "分類", "분류"),
    "Add PDFs to papers/inbox and run a scan to build the dashboard.": (
        "Add PDFs to papers/inbox and run a scan to build the dashboard.",
        "papers/inboxにPDFを追加し、スキャンしてください。",
        "papers/inbox에 PDF를 추가하고 스캔하세요.",
    ),
    "{count} result(s)": ("{count} result(s)", "{count}件", "{count}건"),
    "ID": ("ID", "ID", "ID"),
    "Title": ("Title", "タイトル", "제목"),
    "Year": ("Year", "年", "연도"),
    "Primary Category": ("Primary Category", "主分類", "주 분류"),
    "Classification source": ("Classification source", "分類元", "분류 출처"),
    "Classification": ("Classification", "分類状況", "분류 상태"),
    "AI Provider": ("AI Provider", "AIプロバイダー", "AI 제공자"),
    "AI Model": ("AI Model", "AIモデル", "AI 모델"),
    "Research Methods": ("Research Methods", "研究手法", "연구 방법"),
    "Human reviewed": ("Human reviewed", "人による確認済み", "사람이 검토함"),
    "AI, not reviewed": ("AI, not reviewed", "AI・未確認", "AI · 미검토"),
    "No AI result": ("No AI result", "AI結果なし", "AI 결과 없음"),
    "Unclassified": ("Unclassified", "未分類", "미분류"),
    "Open paper details": ("Open paper details", "論文の詳細を開く", "논문 상세 보기"),
    "No papers match the current filters.": (
        "No papers match the current filters.", "条件に一致する論文がありません。", "조건에 맞는 논문이 없습니다.",
    ),
    "Authors": ("Authors", "著者", "저자"),
    "Venue": ("Venue", "掲載先", "게재처"),
    "Abstract": ("Abstract", "要旨", "초록"),
    "Keywords": ("Keywords", "キーワード", "키워드"),
    "Classified at": ("Classified at", "分類日時", "분류 일시"),
    "AI classification history": ("AI classification history", "AI分類履歴", "AI 분류 이력"),
    "Introduction excerpt (abstract fallback)": (
        "Introduction excerpt (abstract fallback)", "序論の抜粋（要旨の代替）", "서론 발췌 (초록 대체)",
    ),
    "Extraction sources": ("Extraction sources", "抽出元", "추출 출처"),
    "Classification — Human reviewed": (
        "Classification — Human reviewed", "分類 — 人による確認済み", "분류 — 사람이 검토함",
    ),
    "Classification — AI proposal, not reviewed": (
        "Classification — AI proposal, not reviewed", "分類 — AI提案・未確認", "분류 — AI 제안 · 미검토",
    ),
    "Classification — unavailable": ("Classification — unavailable", "分類 — 結果なし", "분류 — 결과 없음"),
    "Relevance reason": ("Relevance reason", "関連度の理由", "관련도 이유"),
    "Confidence": ("Confidence", "確信度", "확신도"),
    "Unknown": ("Unknown", "不明", "알 수 없음"),
    "Unavailable": ("Unavailable", "未取得", "정보 없음"),
    "None": ("None", "なし", "없음"),
    "None extracted": ("None extracted", "抽出なし", "추출된 항목 없음"),
    "No abstract could be extracted.": (
        "No abstract could be extracted.", "要旨を抽出できませんでした。", "초록을 추출하지 못했습니다.",
    ),
    "AI classification unavailable: {error}": (
        "AI classification unavailable: {error}", "AI分類を利用できません: {error}", "AI 분류를 사용할 수 없습니다: {error}",
    ),
    "Human correction": ("Human correction", "人による修正", "사람이 수정"),
    "Select a category": ("Select a category", "分類を選択", "분류 선택"),
    "Select relevance": ("Select relevance", "関連度を選択", "관련도 선택"),
    "Tags (comma-separated; custom tags allowed)": (
        "Tags (comma-separated; custom tags allowed)", "タグ（カンマ区切り・自由入力可）", "태그 (쉼표 구분 · 직접 입력 가능)",
    ),
    "Research methods (comma-separated)": (
        "Research methods (comma-separated)", "研究手法（カンマ区切り）", "연구 방법 (쉼표 구분)",
    ),
    "Target vulnerabilities (comma-separated)": (
        "Target vulnerabilities (comma-separated)", "対象脆弱性（カンマ区切り）", "대상 취약점 (쉼표 구분)",
    ),
    "Save review": ("Save review", "修正を保存", "수정 저장"),
    "Select a primary category and relevance before saving the review.": (
        "Select a primary category and relevance before saving the review.",
        "保存する前に主分類と関連度を選択してください。",
        "저장하기 전에 주 분류와 관련도를 선택하세요.",
    ),
    "Review saved. The original AI values were preserved.": (
        "Review saved. The original AI values were preserved.",
        "修正を保存しました。元のAI値は保持されています。",
        "수정을 저장했습니다. 원래 AI 값은 보존되었습니다.",
    ),
    "Latest AI result (earlier originals in history)": (
        "Latest AI result (earlier originals in history)", "最新のAI結果（過去の原本は履歴へ）", "최신 AI 결과 (이전 원본은 이력에 보관)",
    ),
    "Methods": ("Methods", "研究手法", "연구 방법"),
    "Vulnerabilities": ("Vulnerabilities", "脆弱性", "취약점"),
    "Reason": ("Reason", "理由", "이유"),
    "Manually reviewed": ("Manually reviewed", "人による確認", "사람의 검토"),
    "Yes": ("Yes", "済み", "완료"),
    "No": ("No", "未確認", "미검토"),
    "Scanning new PDFs…": ("Scanning new PDFs…", "新しいPDFをスキャン中…", "새 PDF 스캔 중…"),
    "No valid PDFs found in papers/inbox.": (
        "No valid PDFs found in papers/inbox.", "papers/inboxに有効なPDFがありません。", "papers/inbox에 유효한 PDF가 없습니다.",
    ),
    "Classified": ("Classified", "分類済み", "분류 완료"),
    "Skipped": ("Skipped", "スキップ", "건너뜀"),
    "Failed": ("Failed", "失敗", "실패"),
    "Pending": ("Pending", "分類待ち", "분류 대기"),
    "Needs review": ("Needs review", "要確認", "검토 필요"),
    "Already registered": ("Already registered", "登録済み", "이미 등록됨"),
    "Success": ("Success", "成功", "성공"),
    "Classification retry succeeded": ("Classification retry succeeded", "再分類に成功", "재분류 성공"),
    "Classification held for metadata review": (
        "Classification held for metadata review", "抽出データの確認待ちのため分類を保留", "추출 데이터 검토를 위해 분류 보류",
    ),
    "Classifier is not configured": ("Classifier is not configured", "分類器が未設定です", "분류기가 설정되지 않았습니다"),
    "A reliable title was not found in PDF metadata or first-page layout.": (
        "A reliable title was not found in PDF metadata or first-page layout.",
        "PDF情報や先頭ページから信頼できるタイトルを取得できませんでした。",
        "PDF 정보나 첫 페이지에서 신뢰할 수 있는 제목을 찾지 못했습니다.",
    ),
    "Neither an abstract nor an introduction excerpt was found.": (
        "Neither an abstract nor an introduction excerpt was found.",
        "要旨・序論の抜粋を取得できませんでした。", "초록이나 서론 발췌를 찾지 못했습니다.",
    ),
    "The extracted abstract may contain figure or layout noise.": (
        "The extracted abstract may contain figure or layout noise.",
        "抽出した要旨に図やレイアウトのノイズが含まれる可能性があります。",
        "추출한 초록에 그림이나 레이아웃 잡음이 포함되었을 수 있습니다.",
    ),
    "A trustworthy title is required before classification.": (
        "A trustworthy title is required before classification.",
        "分類には信頼できるタイトルが必要です。", "분류하려면 신뢰할 수 있는 제목이 필요합니다.",
    ),
    "A usable abstract or bounded introduction excerpt is required.": (
        "A usable abstract or bounded introduction excerpt is required.",
        "分類には有効な要旨または短い序論の抜粋が必要です。",
        "분류하려면 유효한 초록이나 짧은 서론 발췌가 필요합니다.",
    ),
    "footer_caption": (
        "Local-first: source PDFs are never moved, renamed, edited, uploaded in full, or committed by default.",
        "ローカルファースト：元のPDFは移動・改名・編集せず、既定では全文送信やコミットもしません。",
        "로컬 우선: 원본 PDF는 이동·이름 변경·편집하지 않으며, 기본적으로 전체 업로드나 커밋도 하지 않습니다.",
    ),
}

TRANSLATIONS = {
    language: {key: row[index] for key, row in _MESSAGES.items()}
    for language, index in (("en", 0), ("ja", 1), ("ko", 2))
}

# Only domain enums have display aliases. Free-form labels remain original text.
_ENUM_LABELS = {
    "Authentication": ("Authentication", "認証", "인증"),
    "Session Management": ("Session Management", "セッション管理", "세션 관리"),
    "Authorization": ("Authorization", "認可", "인가"),
    "Token Security": ("Token Security", "トークンセキュリティ", "토큰 보안"),
    "OAuth / OIDC / SSO": ("OAuth / OIDC / SSO", "OAuth / OIDC / SSO", "OAuth / OIDC / SSO"),
    "Account Management": ("Account Management", "アカウント管理", "계정 관리"),
    "Vulnerability Assessment": ("Vulnerability Assessment", "脆弱性診断", "취약점 진단"),
    "Other Security": ("Other Security", "その他のセキュリティ", "기타 보안"),
    "Unread": ("Unread", "未読", "읽지 않음"),
    "Screened": ("Screened", "確認済み", "검토함"),
    "Read": ("Read", "読了", "읽음"),
    "Important": ("Important", "重要", "중요"),
    "pending": ("Pending", "分類待ち", "분류 대기"),
    "classified": ("Classified", "分類済み", "분류 완료"),
    "failed": ("Failed", "失敗", "실패"),
    "needs_review": ("Needs review", "要確認", "검토 필요"),
}
ENUM_TRANSLATIONS = {
    language: {value: row[index] for value, row in _ENUM_LABELS.items()}
    for language, index in (("en", 0), ("ja", 1), ("ko", 2))
}


def t(key: str, language: str, **values: object) -> str:
    """Get UI text, falling back to English then the key itself."""

    message = TRANSLATIONS.get(language, {}).get(key, TRANSLATIONS["en"].get(key, key))
    return message.format(**values) if values else message


def display_enum(value: str | Enum, language: str) -> str:
    """Render an enum without modifying the input; unmapped values pass through."""

    canonical = str(value.value) if isinstance(value, Enum) else value
    return ENUM_TRANSLATIONS.get(language, {}).get(
        canonical, ENUM_TRANSLATIONS["en"].get(canonical, canonical)
    )


def canonical_from_display(display_value: str, language: str) -> str:
    """Resolve a known enum alias; canonical and unknown labels pass through.

    Widgets use canonical options with format_func, so storage never needs this helper.
    It deliberately does not infer translations for arbitrary human/AI text.
    """

    if display_value in _ENUM_LABELS:
        return display_value
    for canonical in _ENUM_LABELS:
        if display_enum(canonical, language) == display_value:
            return canonical
    return display_value
