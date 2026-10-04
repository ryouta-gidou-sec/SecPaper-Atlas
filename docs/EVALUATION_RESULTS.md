# v0.1.1 Evaluation Results

記録日: 2026-10-03（Asia/Tokyo）。v0.1.1のPrompt tuningは終了。Baseline、Prompt改善①、Final Promptを固定した8本で比較した最終結果を記録する。

## 評価条件

| 項目 | 条件 |
|---|---|
| Baseline evaluation type | 8-paper pilot evaluation |
| Prompt改善後の比較 | development-set comparison / post-prompt-tuning comparison |
| Model | `qwen3:4b` |
| Provider | `local` / Ollama（loopback） |
| Rubric | `v1`（[EVALUATION_RUBRIC.md](EVALUATION_RUBRIC.md)） |
| Normalization | `normalization-v1` |
| Baseline分類履歴 | `classification_runs.id = 2–9`（各PDF hashにつき1件） |
| Prompt改善①の分類履歴 | `classification_runs.id = 10–17` |
| Final Promptの分類履歴 | `classification_runs.id = 18–25` |
| Human Ground Truth | Rubric v1で作成した既存の8件。全件`Reviewed`、review coverage 8/8 |
| 除外件数 | 0件 |
| 証拠範囲 | 保存済みtitle / abstract / keywords。Abstract欠落の1件のみ保存済みIntroduction excerpt |

Ground Truthはローカルの`data/ground_truth.local.csv`を固定して利用する。CSVとDBのHuman値を同期・書換えしない。CSVのレビュー完了条件、版、列挙値、JSON配列、hashとbaseline runの対応、保存済みメタデータとの一致を検証した。

Primary Categoryは完全一致件数 / 8、RelevanceはA/B/Cの一致件数 / 8。Tags / Methods / Target Vulnerabilitiesは、AI・Human双方にRubricに固定された`normalization-v1`だけを適用し、ラベル集合の完全一致件数 / 8を比較する。確認済み空集合`[]`も採点対象に含める。辞書にない語の大小文字、親子概念、原因と結果、Machine LearningとReinforcement Learningを統合しない。元の値は保持する。

## Baseline: 8-paper pilot evaluation

| 指標 | Baseline |
|---|---:|
| Primary Category | 8/8（Accuracy 100%） |
| Relevance | 4/8（50%） |
| Tags: exact match | 0/8（0%） |
| Methods: exact match | 0/8（0%） |
| Target Vulnerabilities: exact match | 2/8（25%） |
| Confidence | 全8件`0.95` |

Relevanceの不一致4件はすべて**AI A → Human B**。baseline run IDは3、4、5、9。自動検査、Web Security、scannerなどの共通点から、セッション研究への直接貢献を過大に判断する傾向があった。

主な失敗傾向:

- Session HijackingをSession Fixationの被害説明等から過剰付与する。
- Browser Automation、Black-box Testingを、HTTP送信・Web対象・自動検査等から過剰付与する。
- Experimental Study、Tool Development、Attack Simulationの明示された実施証拠を拾いきれない。
- Relevance Aの条件を広く解釈する。
- Confidenceが全8件同値で、判断の確実性の違いを表していない。

## Promptの変更範囲

Prompt改善①では`src/classifier.py`の共通SYSTEM_PROMPTだけを調整し、Prompt内の必要な規則を`tests/test_classifier.py`で検証した。

- MethodsはAbstract、欠落時のみIntroduction excerpt中の明示証拠を要求する。Browser AutomationとBlack-box Testingの成立条件と、十分でない証拠を明記する。
- Experimental Studyは実際のtest条件と報告結果、Tool Developmentは提案した実装成果、Attack Simulationは攻撃手順の再現と成否確認を要求する。
- taxonomy / schema / Rubricを確認し、Automated DetectionとVulnerability ScannerをTagsとして扱い、Methodsに含めない。
- Tagsの背景・一般概念・親概念・被害からの自動展開を抑える。Target Vulnerabilitiesは直接対象の具体的クラスだけとし、Fixationの結果からHijackingを追加しない。
- Relevance Aはセッション研究への直接貢献、またはRubric v1の3条件を満たす具体的な汎用評価方法に限定する。転用可能な関連研究はBとする。
- Confidenceはevidence strengthとclassification certaintyに応じて判断し、`0.95`等の固定値を使わないよう指示する。校正機能は追加しない。

Final PromptではPrimary Categoryの判定規則だけを追加した。研究目的、提案手法が直接扱うセキュリティ対象、主要貢献、実験・評価結果の順に判断し、具体的な対象を検出・診断手法より優先する。脆弱性発見が評価結果であるだけならVulnerability Assessmentへ寄せない。AUTHSCAN専用の規則や、論文タイトル・filenameによる分岐は追加していない。Tags、Methods、Target Vulnerabilities、Relevance、Confidenceの判定規則はPrompt改善①から変更していない。

taxonomy、normalization-v1、Ground Truth、Rubric v1、PDF、metadata extraction、database schema、Streamlit UI、Provider abstraction、Ollama integrationは変更しない。保存・入力経路は既存の共通分類器と`Database.update_classification`を利用する。

## Post-prompt-tuning: development-set comparison

Prompt改善①の実行日時: 2026-10-03 00:52:41–00:57:33（Asia/Tokyo）。**再分類8/8件成功、失敗0件**。schema validationを通った元の分類値を、新しいrun ID **10–17**として保存した。

Final Promptの実行日時: 2026-10-03 01:06:37–01:12:08（Asia/Tokyo）。**再分類8/8件成功、失敗0件**。新しいrun ID **18–25**として保存した。既存run ID 1を含め、baseline 2–9とPrompt改善①の10–17を保持した。各段階は1論文につき1件で、評価分母は常に8。

Ollama `0.35.0`、モデル`qwen3:4b`（Q4_K_M）。既存の推論条件を維持した: `temperature=0`、`think=false`、`num_ctx=8192`、`num_predict=1024`、timeout 180秒、validation retry上限1回。PDFの再抽出は行わず、baseline参照CSVと一致する保存済みメタデータを使った。`processing_seconds`は既存のscan全体の計測値なので更新していない。

Prompt改善①のSHA-256: `fa7cd7748e6655c62c9b83eedea7c24540cd0e07a2d12404c7c193bce7de00b6`。

Final PromptのSHA-256: `cc063dea4ef57d1677220bb6667c5cf3ce1fa1c5ade0010e4b515dfcd276feb8`。調整開始時HEAD: `db8a8ac62ff560062ab8e9b71851c638edff78f1`、branch: `fix/metadata-extraction`。

| 指標 | Baseline（2–9） | Prompt改善①（10–17） | Final Prompt（18–25） |
|---|---:|---:|---:|
| Primary Category | 8/8（100%） | 7/8（87.5%） | 8/8（100%） |
| Relevance | 4/8（50%） | 5/8（62.5%） | 4/8（50%） |
| Tags: exact match | 0/8（0%） | 0/8（0%） | 0/8（0%） |
| Methods: exact match | 0/8（0%） | 0/8（0%） | 0/8（0%） |
| Target Vulnerabilities: exact match | 2/8（25%） | 7/8（87.5%） | 6/8（75%） |
| Confidence分布 | 全件0.95（0.95 × 8） | 0.95 × 6、0.85 × 2 | 0.95 × 7、0.80 × 1 |
| Confidence範囲 / 平均 | 0.95–0.95 / 0.95 | 0.85–0.95 / 0.925 | 0.80–0.95 / 0.93125 |

AUTHSCANのPrimary Categoryは、BaselineのAuthentication → Prompt改善①のVulnerability Assessment → Final Promptの**Authentication**。FinalではHuman Ground Truthと一致した。

セット完全一致だけでは部分的な変化を表せないため、補助的に全論文のラベル単位のTP / FP / FNも示す。micro F1は`2TP / (2TP + FP + FN)`。真陽性・過剰付与・見逃しを両側で同じ正規化を適用した後に数える。

| Field | Baseline TP / FP / FN | Prompt改善① TP / FP / FN | Final TP / FP / FN | micro F1: Baseline → ① → Final |
|---|---|---|---|---|
| Tags | 19 / 21 / 11 | 21 / 25 / 9 | 20 / 23 / 10 | 0.543 → 0.553 → 0.548 |
| Methods | 3 / 18 / 12 | 5 / 11 / 10 | 3 / 12 / 12 | 0.167 → 0.323 → 0.200 |
| Target Vulnerabilities | 7 / 8 / 0 | 7 / 2 / 0 | 7 / 3 / 0 | 0.636 → 0.875 → 0.824 |

### Run対応と単一ラベルの結果

全baselineのConfidenceは0.95。以下のRelevanceは「Baseline → ① → Final / Human」を表す。

| Baseline run | ① run | Final run | Human / Final Category | ① Category | Relevance | ① / Final Confidence |
|---:|---:|---:|---|---|---|---|
| 2 | 10 | 18 | Session Management | Session Management | A → A → A / A | 0.95 / 0.95 |
| 3 | 11 | 19 | Authentication | Vulnerability Assessment | A → A → A / B | 0.85 / 0.95 |
| 4 | 12 | 20 | Vulnerability Assessment | Vulnerability Assessment | A → A → A / B | 0.95 / 0.95 |
| 5 | 13 | 21 | Vulnerability Assessment | Vulnerability Assessment | A → B → A / B | 0.85 / 0.80 |
| 6 | 14 | 22 | Session Management | Session Management | A → A → A / A | 0.95 / 0.95 |
| 7 | 15 | 23 | Session Management | Session Management | A → A → A / A | 0.95 / 0.95 |
| 8 | 16 | 24 | Session Management | Session Management | A → A → A / A | 0.95 / 0.95 |
| 9 | 17 | 25 | Vulnerability Assessment | Vulnerability Assessment | A → A → A / B | 0.95 / 0.95 |

### Prompt改善①で観測した改善・悪化

- **改善:** Target Vulnerabilitiesの過剰ラベルは8個から2個に減少し、見逃しは0個のまま。Session HijackingのTarget誤付与は3件から1件になった。具体的対象のないrun 13では空集合を返した。
- **改善:** run 13のRelevanceがAから正解のBへ修正された。Browser AutomationのMethods誤付与は7件から2件に減少。Experimental Studyの見逃しは5件から4件、Attack Simulationは2件から1件に減少した。
- **悪化:** run 11でPrimary Categoryが正解のAuthenticationからVulnerability Assessmentへ変わり、中心指標は7/8へ低下した。このregressionは後述のFinalで修正された。
- **悪化:** Tagsの過剰付与が21個から25個に増加。見逃しは減ったが、完全一致は改善せず、micro precisionも0.475から0.457へ低下した。micro F1の微増だけを成功と扱わない。
- **未解決:** MethodsのBlack-box Testing誤付与は6件のまま。Tool Developmentの見逃しは3件のまま。禁止を明記しても、Automated Detectionが2件、Vulnerability Scannerが1件のMethodsに残った。
- **未解決:** Relevanceの残る不一致3件（run 11、12、17）はすべてAI A / Human B。CSRF・SQL Injection等の自動検査を、セッションへの直接貢献として扱う誤りが残る。run 11ではHumanのTarget空集合に対してSession FixationとSession Hijackingを推測している。
- **未解決:** Confidenceは2種類になったが、6件は依然0.95。不一致にも高値を返しており、値が分かれたことは校正の改善を意味しない。

### Final Promptの解釈と残る課題

- **Primary Category:** Finalはbaselineの8/8を維持した。AUTHSCANはAuthenticationに戻り、①で発生した唯一のCategory regressionを修正した。
- **Target Vulnerabilities:** baseline 2/8からFinal 6/8へ改善した。過剰ラベルは8個から3個に減り、見逃しは0個のまま。ただし①の7/8からは低下し、run 23でSession HijackingにSession Fixationが余分に追加された。
- **過剰推定の抑制:** Browser AutomationのMethods誤付与はbaselineの7件からFinalの1件、Tagsでは3件から1件に減った。Session HijackingのTarget誤付与も3件から1件へ減少した。抑制はこのdevelopment setで観測された範囲に限る。
- **Tags / Methods:** 完全一致は依然ともに0/8で課題が残る。Black-box TestingやAutomated DetectionのMethodsへの過剰付与、Tool Development等の見逃しが残る。①からFinalで補助的なmicro F1も低下した。
- **Relevance:** 依然4/8で、Aへの過大評価が残る。Finalの不一致4件（run 19、20、21、25）はすべてAI A / Human B。①でBだったrun 13がFinalのrun 21ではAとなり、5/8から4/8へ戻った。
- **段階間の変動:** Prompt改善①とFinal Promptの間で、RelevanceとTarget Vulnerabilitiesに変動があった。これらの判定規則自体はFinalで変更していないため、local LLMのrun-to-run variabilityが影響した可能性がある。ただしPrimary CategoryのPrompt追加により入力文脈も変わっており、同一Promptを反復する対照実験ではない。変動をvariabilityだけに帰属したり、その大きさを測定したとは扱わない。
- **Confidence:** Finalは0.95 × 7、0.80 × 1。自己申告値であり、校正済み確率ではない。不一致にも高値を返しており、Confidenceの分布変化を校正改善とは解釈しない。

この比較は**development-set comparison**であり、独立test-setによる一般化性能評価ではない。独立したholdoutは用意していない。将来の一般化性能評価には、Prompt調整に使っていない論文と十分な各Categoryのsupportが必要。完成を優先してPrompt tuningを終了し、再分類後の追加調整は行わない。

## 検証と完成準備

変更前: `104 passed in 27.94s`。Prompt改善①後: `126 passed in 13.14s`。Final Prompt後: `.venv/Scripts/python.exe -m pytest`で**`130 passed`**。①で証拠範囲、Methodsの成立／除外条件、対象脆弱性の非拡張、A/B条件、Confidence指示を検証する22ケース、FinalでPrimary Categoryの優先順位と対象・手法・評価結果の区別を検証する4ケースを追加した。これはPrompt内の規則の存在を検証するテストであり、LLMの遵守や分類精度を保証するものではない。

各段階の実行前後の照合で、すべての元classification history、Ground Truth CSVのbytes、inboxの全ファイルのhash、Human current値、メタデータ、DB schema、既存のprocessing_secondsの保持を確認した。①とFinalでそれぞれ分類履歴8件を追記し、既存仕様に従って最新のAI projectionを更新した。DBのSQLite backupをローカルに保存した。今回の最終文書更新ではコード変更・再分類を行わない。

個別のAI原値、Human値、正規化後の差分、入力payload hash、保全監査は、Gitから除外される`logs/v011-prompt-tuning/`と`logs/v011-primary-comparison/`に保存した。①の記録にはモデルdigestも含む。実行・集計用の一回限りの補助scriptも`logs/`内にあり、アプリ機能や既存の`evaluate.py`を拡張していない。研究データやDBを成果物のcommit対象に含めない。

Primary Category regressionの修正を確認し、v0.1.1の評価・最終調整を完了した。multi-labelとRelevanceの課題は残り、8本の結果から一般的なリリース品質やモデル性能を保証しない。その後mainへ統合し、v0.1.1をローカル完成版としてタグ付けした。GitHub公開操作は未実施。

## カテゴリ分布と解釈の限界

| Human Category | support | Baseline Precision / Recall / F1 | ① Precision / Recall / F1 | Final Precision / Recall / F1 |
|---|---:|---|---|---|
| Authentication | 1 | 1.000 / 1.000 / 1.000 | 0.000 / 0.000 / 0.000 | 1.000 / 1.000 / 1.000 |
| Session Management | 4 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 |
| Vulnerability Assessment | 3 | 1.000 / 1.000 / 1.000 | 0.750 / 1.000 / 0.857 | 1.000 / 1.000 / 1.000 |
| Authorization | 0 | 未評価 | 未評価 | 未評価 |
| Token Security | 0 | 未評価 | 未評価 | 未評価 |
| OAuth / OIDC / SSO | 0 | 未評価 | 未評価 | 未評価 |
| Account Management | 0 | 未評価 | 未評価 | 未評価 |
| Other Security | 0 | 未評価 | 未評価 | 未評価 |

①のAuthentication予測件数は0件なのでPrecisionの分母も0。表の0.000は既存計算規約での値であり、観測されたPrecisionではない。

8論文・出現3Categoryだけのpilotであり、support=0のCategoryは性能未評価。100%という値はこの8件のPrimary Category一致率だけを示し、`qwen3:4b`の一般性能を示さない。

この8論文の失敗パターンをPrompt改善に利用しているため、改善後の比較は**development-set comparison**である。独立したtest-set evaluationとは呼ばず、一般化性能の向上を主張しない。Confidenceはモデルの自己申告値であり、実測Accuracyや校正済み確率ではない。

## Evaluation Dataset v1: formal heldout evaluation

記録日: 2026-10-04（Asia/Tokyo）。IDs 1–8 は development / historical tuning、IDs 9–40 の **32本のみ**を正式 heldout として固定した。上記8本の開発比較とは別の集計であり、合算値は出さない。

**GT provenance:** AI-assisted Ground Truth draft, independently reviewed and finally approved by a human reviewer. 人間は32本すべての5項目候補を修正なしで最終承認した。候補値は再解釈せず転記し、既存8件のGTは変更・再レビューしなかった。

個別の frozen AI prediction は候補判断に使用せず、draft作成中の予測比較も行っていない。ただし preflight でmanifest全体の表示操作（出力は省略）とtooling内の集計assertion閲覧があった。このdocumented procedural deviationにより、strict non-exposure blindingは認定できない。予測に合わせてGTを変更したという事実を示すものではない。

| 条件 | 値 |
|---|---|
| Dataset | evaluation-dataset-v1 |
| Formal cohort | heldout IDs 9–40; n=32; exclusions=0 |
| Development excluded | IDs 1–8; historical tuning |
| Provider / Model | local / Ollama; qwen3:4b |
| Rubric / Normalization | v1 / normalization-v1（変更なし） |
| Protocol | evaluation-protocol-v1; 評価前固定 |
| Prediction selection | freeze時点のcurrent AI predictionのみ |
| Independent cross-check | 全metric・support・count・confusion matrixが完全一致、PASS |
| Full test suite | 524 passed（既存495 + 追加29） |

モデルdigestはfreeze時に観測したインストール済みモデルのidentityである。classification historyには過去runごとのmodel digestが保存されていないため、各runの実バイナリまで認定するものではない。今回モデルserverへのrequest・再分類・prompt変更はない。

### Heldout metrics (n=32)

| Field | Accuracy / Exact Match | Micro P | Micro R | Micro F1 | Macro P | Macro R | Macro F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Primary Category | 0.750000 | 0.750000 | 0.750000 | 0.750000 | 0.844048 | 0.808333 | 0.767956 |
| Relevance | 0.093750 | 0.093750 | 0.093750 | 0.093750 | 0.233716 | 0.444444 | 0.170370 |
| Research Methods | 0.156250 | 0.309091 | 0.265625 | 0.285714 | 0.167002 | 0.163402 | 0.118162 |
| Tags | 0.000000 | 0.250000 | 0.340741 | 0.288401 | 0.154310 | 0.152299 | 0.150527 |
| Target Vulnerabilities | 0.437500 | 0.160000 | 0.200000 | 0.177778 | 0.106061 | 0.101010 | 0.095960 |

Primary Accuracy=24/32、Relevance Accuracy=3/32。Exact Match は Tags=0/32、Methods=5/32、Vulnerabilities=14/32。

Primaryのmacroは固定8分類、Relevanceは固定A/B/C。単一ラベルmicro P/R/F1はAccuracyと等しい。multi-labelのmacroはheldout GTまたはpredictionに出現したlabel union上で計算し、zero division=0。双方空集合はexact matchに含め、空union macro=0。正規化はRubricの明示辞書と空白整理・完全一致重複排除のみ。未登録語の大小文字・親子概念は保持した。

### Primary Category: per-class metrics

| Class | GT Support | Predicted | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|
| Account Management | 5 | 3 | 1.000000 | 0.600000 | 0.750000 |
| Authentication | 4 | 5 | 0.800000 | 1.000000 | 0.888889 |
| Authorization | 6 | 4 | 1.000000 | 0.666667 | 0.800000 |
| OAuth / OIDC / SSO | 5 | 4 | 1.000000 | 0.800000 | 0.888889 |
| Other Security | 5 | 2 | 1.000000 | 0.400000 | 0.571429 |
| Session Management | 1 | 1 | 1.000000 | 1.000000 | 1.000000 |
| Token Security | 4 | 6 | 0.666667 | 1.000000 | 0.800000 |
| Vulnerability Assessment | 2 | 7 | 0.285714 | 1.000000 | 0.444444 |

Confusion matrix（行GT、列AI、固定class order）:

| GT / AI | Authentication | Session Management | Authorization | Token Security | OAuth / OIDC / SSO | Account Management | Vulnerability Assessment | Other Security |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Authentication | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Session Management | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| Authorization | 0 | 0 | 4 | 2 | 0 | 0 | 0 | 0 |
| Token Security | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 |
| OAuth / OIDC / SSO | 0 | 0 | 0 | 0 | 4 | 0 | 1 | 0 |
| Account Management | 1 | 0 | 0 | 0 | 0 | 3 | 1 | 0 |
| Vulnerability Assessment | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 |
| Other Security | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 2 |

### Relevance: per-class metrics

| Class | GT Support | Predicted | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|
| A | 1 | 29 | 0.034483 | 1.000000 | 0.066667 |
| B | 25 | 0 | 0.000000 | 0.000000 | 0.000000 |
| C | 6 | 3 | 0.666667 | 0.333333 | 0.444444 |

Confusion matrix（行GT、列AI、固定class order）:

| GT / AI | A | B | C |
|---|---:|---:|---:|
| A | 1 | 0 | 0 |
| B | 24 | 0 | 1 |
| C | 4 | 0 | 2 |

### Error patterns and limitations

- Primaryでは Other Security → Vulnerability Assessment が3件、Authorization → Token Security が2件。残りはAccount Management → Authentication / Vulnerability Assessment各1件、OAuth / OIDC / SSO → Vulnerability Assessmentが1件。
- Relevanceでは GT B → AI A が24件、GT C → AI A が4件、GT B → AI C が1件。直接関心への一致を広く判定する傾向がある。
- Tags: TP=46 / FP=138 / FN=89。過剰付与が不足付与より多い。
- Methods: TP=17 / FP=38 / FN=47。不足付与が過剰付与より多い。
- Vulnerabilities: TP=4 / FP=21 / FN=16。過剰付与が多い。14/32のexact matchと低いF1の両方を読む必要があり、exact matchだけで肯定ラベルの再現性を主張しない。

n=32、Primary support=1–6、Relevance A support=1という小規模・不均衡集合である。1名の人間reviewer、AI-assisted候補、既知のblinding逸脱があり、一般化性能や完全に独立したmanual-only annotationを主張しない。各フィールドで語彙・GTの疎密が違うため、F1差だけを共通の難易度尺度にはしない。

証拠範囲はfreezeされたtitle / abstract / keywords、abstract欠落時のみ短いintroduction excerpt。全文に存在する手法すべての網羅性ではなく、この証拠範囲で支持されるラベルを評価する。Confidenceの校正は評価していない。原PDF、DB、metadata、AI prediction、history、Human Review、source GT、freeze、Rubric、promptは保全検証で不変。

### Reproducibility identities

| Identity | SHA-256 |
|---|---|
| Dataset content | `2852837d2aeccc8671ad76a28173fdc063e8c8dbccb93dc4562972c8715748db` |
| Freeze manifest | `1385d3f5c5d628c7f80e9e8db00c198da87c2d84df8ff837a0f19f400f1082c1` |
| Frozen DB snapshot | `bde660d567237a51388300c45917413936d817e8e4c26627ca7adbc568870cda` |
| Human-approved GT v1 | `3bea5bba3f3b88c2d0086d66f029952da426828d66b94b468c84be487da4d883` |
| Split v1 | `3dfbc9c0bc45479a17b65901c2fbf4d4df113ee28446444a5f0bd4771104aa54` |
| Frozen AI predictions (40) | `0ad0cb62ba7248a2a505a97f2e03b2ecd175dbcf6978f67a9ae4a677cf8e5ce0` |
| Heldout AI predictions (32) | `19ec05c1b33f2b7d99668d1a8375a8a4e2c272462817af63b5ba8b68c924f1a5` |
| Rubric v1 | `e49ae70b8d48a1febf25c719f9df8c35cd4dbeff3b263c45c038a78de84da5ce` |
| Evaluator sources (evaluate.py + evaluation_v1.py) | `9a174116ed741d67f74ecb42175713ca9a8418cbecf1282af9db4cf15c51fafe` |
| Protocol v1 | `aee6be6196d392ba5926f6815e63f5c5e9364dda7cf120146fe29431a347c068` |
| Prompt | `b9b7fdddae0c1375de55b9cf8d55d7f83dd6a202ef5fe36c3674132010fda4dd` |
| Model observed at freeze | `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7` |
| Deterministic evaluation content | `e1a444632bfbfd0830ab13aecd255d82640ecc0fc3ce2891fccee3ef8e4ea150` |
| Metrics content | `2e13cac450373f98d3898d278aba678dad6093d6589e7c7ff4e290bbafd3adb5` |

content digestはUTF-8 canonical JSON（sort_keys、compact separators、ensure_ascii=False、allow_nan=False）のSHA-256。timestampはidentityへ含めない。GT・split・protocol・evaluator sourceは評価前にlockし、評価後のdigest一致を確認した。個別GT、title/hash一覧、raw結果、private audit artifactは公開しない。

### No heldout tuning

**Evaluation Dataset v1 / heldout IDs 9–40は、今回の正式評価後、classifier prompt tuningに使用しない。** この結果を見てprompt・model設定・normalization・taxonomy・GTを変更したり、AI predictionを再生成したりしない。改善はdevelopment IDs 1–8または新規development corpusで行い、新しいindependent test setで評価する。今回の作業は正式評価と記録で終了した。
