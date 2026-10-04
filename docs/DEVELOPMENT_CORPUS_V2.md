# Development Corpus v2

## Purpose

SecPaper-AtlasのClassifier v2開発に使う、新規32論文のDevelopment Corpusを準備した。論文の選定、公開PDFの取得、入力Evidenceの固定、blind review packetの作成までを完了している。**freezeしたのはcorpus identityであり、Ground Truthではない。** 分類の実行やv2実装は次の段階となる。

仕様のauthorityは[Classifier v2 Plan](CLASSIFIER_V2_PLAN.md)と[Evaluation Rubric v1](EVALUATION_RUBRIC.md)。本書はその収集結果と監査方法を説明する。個別論文の仮ラベルやGTは掲載しない。

## Why a new corpus was necessary

v1の評価を受けて、v2ではEvidenceに支えられた分類、厳密なSession Relevance、Primaryの対象判定を改善する計画を立てた。しかし、既に評価に使った論文を調整用に転用すると、既知の評価例への適合を改善と誤認するおそれがある。そのため、既存40論文から独立した開発用corpusを新たに作った。

この32本は開発用であり、独立Testではない。今後の開発スコアをv1の旧heldoutスコアと直接比較して性能向上を主張しない。正式な比較には、別途用意する未露出Test上でのv1/v2比較が必要となる。

## Separation from Evaluation v1

既存40論文、production DB、72件のclassification history、Evaluation Dataset v1、Human-approved GT v1、split-v1、評価結果、frozen predictions、v1 Prompt、taxonomy、normalization-v1、Rubric、v2 Planを保全した。

開始前に既存ファイルのSHA-256・サイズ・更新時刻を取得し、終了時に照合した。9,538ファイルが一致し、DBは40 papers / 72 classification runsのまま。DBは読み取り専用・immutable接続で件数と重複照合用の書誌identityだけを確認し、登録やmetadata refreshは行っていない。既存inboxのPDF40本も変更していない。

## Leakage prevention

旧heldoutの個別prediction、GT、error、abstractを選定材料として参照していない。探索の出発点はv2 Planで固定済みのaggregate方針のみとした。既存論文のtitle・author・year・PDF hash・persistent IDは、隔離した重複照合用registryで機械的に比較した。旧論文の内容や判定値を新規候補のEvidenceへ転記していない。

選定用のprovisional strataとblind packetは別ファイルに保存した。前者はassistantによる選定上の判断であり、GTやclassifier predictionではない。人間のreviewerにはblind packetだけを渡し、selection manifestやこの公開集計を個別判定のヒントとして渡さない。

## Eligibility criteria

採用対象はSecurity研究で、次をすべて確認できる論文とした。

- 正当な公開元から取得でき、PyMuPDFで読めるfull-text PDF。
- title、authors、year、venueまたはpreprintのpublication identity。
- 判定に使用できる原文abstract。abstractが欠落した場合に限り、Rubricの短いintroduction fallbackを許容する。
- 既存40論文や候補間に、同一研究または未解決の重複疑いがないこと。

会議公式ページ、author公開ページ、arXiv、大学repository、J-STAGE等を探索した。選定32本はすべてabstractありで、introduction fallbackは0本。取得に失敗したURLやPDFではない応答は記録し、TLS検証やアクセス制限を回避して採用していない。

## Duplicate control

PDF SHA-256、Unicode NFKC・casefold・英数字化したtitle identity、DOI、arXiv ID、author/year/titleの組合せを照合した。authorを共有する近似titleは自動採用せず、同一研究のpreprint・published・extended versionかを確認した。この書誌用title keyは、評価ラベルのnormalization-v1とは別用途である。

既存40本と同一研究の候補9本を除外した。取得済み候補のPDF byte重複は0件、候補内部の同一研究重複も0件。内部のauthor/title近似1組は、abstractに示された研究課題・成果物と著者構成・年・公開identityの違いを確認して別研究と判断し、解決理由を記録した。最終32本は異なる研究・異なるPDF hashで構成する。

ここで9件は同一研究の除外件数であり、「title一致9件」と別に足し合わせない。すべてを異なる版のPDFを取得して確認したという意味でもない。既存workと判定した候補のPDFは重複を承知で再取得していない。

## Candidate selection protocol

候補登録・仮ラベル付与前に、`development-selection-v2-v1`をlocal-onlyで固定した。事前の広い探索queryは開示し、その検索で見えたidentityもTest除外へ追加した。

探索対象は2000–2026年、英語と日本語。queryはsession cookie/logout/revocation、authentication/MFA/FIDO、authorization、JWT/token、OAuth/OIDC/SSO、account recovery、scanner/browser automation/state-aware testing等の系列を用いた。候補を発見順に登録し、許可された原文Evidenceを確認した。発見順を基本としつつ、Evidence品質・重複・Primary/Relevance・hard negatives・研究手法の条件を同時に満たすよう選定し、順序の例外と理由を別途記録した。

| 状態 | 件数 |
|---|---:|
| 詳細確認したcandidate papers | 73 |
| 新規・非重複でPDF取得とeligibility確認済み | 61 |
| Selected | 32 |
| Reserve | 12 |
| Rejected（reserveを含まない） | 29 |
| Rejectedのうち既存work | 9 |

73本は目安の50–70本を少し超える。厳密なAと多様な代替候補を確保するため追加探索を続け、最低48 eligible candidatesの目標を満たした。採用しなかった候補にもrejection/reserve理由を残した。

## Corpus size and diversity

32本固定。選定後にnormalized title、persistent identityの順で並べ、production DBとは独立した`DV2-001`–`DV2-032`を決定した。

選定PDF合計は68,938,644 bytes（約65.7 MiB）。全32本が非ゼロサイズ、PDF signature確認、SHA-256固定、PyMuPDF可読、page count > 0を満たす。取得元・redirect後URL・hash・サイズ・取得結果をlocal-only logに残す。

英語31本、日本語1本。登録した公開版の年は2008–2026年、13の異なる年にまたがる。USENIX Securityが25本、arXiv公開版が4本、ESSoS・Security Protocols Workshop・大学ICT推進協議会年次大会が各1本。arXivは公開版identityとして記録しており、査読venueの代替を主張するものではない。

USENIXへの偏りは残る。日本語4–8本の任意目安も未達である。言語数を満たすために取得・Evidence・研究対象の基準を緩めてはいない。

## Primary balance policy

8カテゴリ各3–5本を目安とし、対象に自然に対応する研究を優先した。次の値は**選定用の仮集計**であり、human GTの分布ではない。

| Provisional Primary | 本数 |
|---|---:|
| Authentication | 5 |
| Session Management | 5 |
| Authorization | 3 |
| Token Security | 4 |
| OAuth / OIDC / SSO | 4 |
| Account Management | 3 |
| Vulnerability Assessment | 5 |
| Other Security | 3 |

## Relevance balance policy

A/B/C各8本以上を目標とし、仮集計はA=8、B=15、C=9。Aはweb sessionへの直接性を保守的に判断し、generic web assessmentについてもPlanの3 gateを要求した。Bは技術・手順の具体的な転用先と必要な適応を確認し、単に「役立ちそう」という理由では付けない。Cでは原文Evidenceに具体的なsession診断手順があると推測しない。仮分布は後のhuman reviewで変わり得る。

## Hard-negative policy

「Aと誤認しやすいが、Evidence上は直接Session研究とは限らない」例を、12 distinct papersとして確保した。1論文を複数系列の本数へ重複計上していない。

| 選定上の系列 | 本数 |
|---|---:|
| Authentication without session subject | 2 |
| OAuth / OIDC without session subject | 2 |
| JWT / token without session subject | 2 |
| Non-session-specific scanner | 2 |
| Browser automation without session subject | 2 |
| State-aware testing without session subject | 2 |

hard-negative群の仮RelevanceはB=7、C=5。designationと理由はselection manifestだけに保存し、blind packetから除外した。

多様性の選定上の目安として、明示的vulnerabilityがない候補17本、単一9本、複数6本を含む。少数topic候補12本、多数14本、formal/theoretical 6本、empirical/experimental 15本、tool development 11本、user study 2本を確認した。研究手法の集計は重複可能。これらは密度・研究形態の見積もりであり、Tags/Methods/VulnerabilitiesのGT候補値を作成したものではない。

## Evidence scope

後のclassifier inputとGT reviewには同じ固定Evidenceを使用する。

- 原文title（最大500文字）。
- 取得PDFのabstract（最大6,000文字）。
- 実際に記載されたkeywords（最大30項目）。推測追加しない。
- abstractがない場合だけ短いintroduction excerpt（最大2,500文字）。今回の使用は0件。

既存PDF parser / metadata extractorを読み取り専用・in-memoryで利用した。PDF本文は書誌確認に使えても分類Evidenceへ混ぜない。title妥当性、abstractの有無と完結性、header/reference混入、keywords、encodingを確認した。

一部で公開ページと取得PDFのabstractが異なったため、取得した版のPDF abstractをcanonicalにした。また、abstractの段組による途中切れをlocal helperで補正した。元の抽出値と修正根拠は別auditに保存する。日本語を英訳せず、PDF由来の改行・ligature等を整理して原文を保持した。runtime extractor自体は変更していない。

## Blind Ground Truth workflow

`blind-review-packet.json`と人間用`blind-review.md`に32本のidentityと許可されたEvidenceを収録した。JSONは固定allowlistで生成・検証し、selection hints、prediction、confidence、history、expected labelsを含まない。MarkdownのPrimary/Relevance/Tags/Methods/Vulnerabilities欄とapproval checkboxは未記入のまま。

独立reviewerはblind packetから原文Evidenceを読み、Rubric v1に従って判断する。未記入と「明示的に空集合と判断した値」を区別する。selection manifestをreviewerへ渡さず、GT review中に論文を入れ替えない。corpus acceptanceに問題があれば、理由を記録して別versionでsupersedeする。

今回、GT draft、human label入力、GT approval/freeze、classifier predictions、provider classification requestsはすべて0。Prompt・schema・provider・runtimeも変更していない。

## Future independent Test Set separation

selectedだけでなくrejectedとreserveを含む73本すべてを`development_exposed=true`として記録した。同一研究の別版も将来の独立Testから除外する。

探索では公式programの1,906 title entriesも機械列挙し、検索結果のtitle/snippetと合わせて保守的な除外registryへ登録した。統合後は**2,134 source identity entries**。これはdistinct research papersの厳密な本数ではない。会議案内・invited talk・不完全なtitle・別版identityを含むため、詳細確認した73論文と区別する。

初期検索の一部はidentity captureが不完全なため、該当するUSENIX/NDSSの会議年度やworkshop全体を除外するsource barrierも保持する。未知identityを「73本にないからTestで使用可」と扱わない。次のTest選定ではregistry、same-work aliases、source barrierを必ず確認し、不明なものは除外する。この広い除外範囲は、将来の利用可能な母集団を狭めるという制約を伴う。

## Reproducibility

選定protocol、全候補のidentity/判断、取得log、選定PDF、入力JSON、抽出audit、duplicate audit、reserve、保全fingerprint、manifestをlocal-onlyで保持する。stable IDにPDF hash・サイズ・metadata digest・Evidence/input digest・source URLsを結び付けた。取得版と固定入力を同じidentityで照合できる。

SHA-256の対象は、sorted keys、compact separators、UTF-8、`ensure_ascii=False`、`allow_nan=False`のcanonical JSON。digestは対象contentの外に置き、UTC/JST timestampをcorpus content digestに混ぜない。候補poolも取得時刻を除いてcontentを固定した。Rubric/Planのhash、protocol identity、normalization版、作業開始Git HEADも記録する。

| Identity | SHA-256 |
|---|---|
| Corpus content | `3a5ad8f5ffae0c38ff80d8669184aa432a4d81ab8d4f6245c02c1ee670d86cdd` |
| Candidate pool content | `4e9dc5c8a7e3f06d78734071e9f95ea946469deca79c3832f0ae0e7cd500b14c` |
| Future Test exclusion content | `711ba2085994bf4f8fd3dc4c7e94d71fa62203187b49f1e8da55e111a06cfdc1` |

resume auditで、取得失敗log2件の欠損項目をunknownの`null`として補い、manifestのprotocol版名を既存protocolと一致させた。修正前artifactを保存し、版名補正後のcorpus digestを上記の正式identityとした。論文・PDF・stable IDs・入力・仮strata・blind packetの内容は変更していない。

Gitの公開文書からは設計・選定方法・aggregate結果・content commitmentを検証できる。PDFと固定入力を公開していないため、このrepositoryだけで同じbyte/inputを取得して全digestを再計算できるとは主張しない。完全な再計算にはlocal-only artifactが必要で、公開元のPDF差替えも同一byteを保証しない。

## What is intentionally not published

PDF、full abstractの大量転載、candidate pool、acquisition log、paper-level provisional labels、selection manifest、blind packet、corpus manifest、reserve list、private audit、GT、prediction、SQLite、秘密情報、絶対ローカルパスはGitへ追加していない。公開するのはこの方法文書とaggregate集計・digestだけ。既存ignoreでlocal corpus全体が対象となるため、新しいignore ruleは追加していない。

## Next step

まず人間がcorpusの対象・取得版・Evidence品質を最終確認する。その後、selection hintsに未露出のreviewerへblind packetを渡し、Rubricに基づくGT reviewとhuman approvalを行う。GTの確定とinput identityの再照合が済んでから、v2実装・最大3 iterationのDevelopment tuning・独立Test準備へ進む。今回はcorpus準備とblank packetの作成までで停止する。
