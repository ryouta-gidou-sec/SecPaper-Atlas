# Evaluation Rubric v1

## 1. 適用範囲と版管理

| 項目 | 値 |
|---|---|
| Rubric version | `v1` |
| Normalization version | `normalization-v1` |
| 作成日 | 2026-10-02（Asia/Tokyo） |
| 中心評価 | v0.1.1のPrimary Category Accuracy |
| 対象 | 保存済みLocal LLM（qwen3:4b）の8本を、人間が独立にレビューするための基準 |

この文書は評価基準を定義する。各論文の正解ラベルを決定したり、Human Ground Truthを入力したりするものではない。末尾のChecklistも確認事項であり、正解一覧ではない。AI Prediction、AI理由、Confidenceは人間の判断根拠にしない。

既存の一般的な評価手順は[EVALUATION.md](EVALUATION.md)を参照する。今回の8本の判断基準、完了条件、正規化は本書に従う。コード、Prompt、保存構造、分類結果は変更しない。

レビュー開始前にこの基準を固定する。基準の意味を変える場合は別版とし、変更理由と対象を記録して同じ評価集合を一貫して再レビューする。AIとの一致率を上げるために個別の例外を作らない。研究関心の変更もRelevance基準の版変更として扱う。

### 判断の順序と証拠範囲

1. AI列を可能な限り非表示にし、タイトルとAbstractを読む。Abstractがない場合だけ保存された短いIntroduction excerptを代用する。
2. 論文の「主要な研究対象」「主要貢献」「実施した研究手法」「直接対象の脆弱性」を別々に一文で整理する。
3. Category、Relevance、Tags、Methods、Target Vulnerabilitiesをそれぞれ独立に判断し、証拠位置と理由を残す。
4. 全Human項目が確定してからAI列を参照し、食い違いの原因を確認する。AIに合わせてHuman値を変更しない。

**v1の評価証拠範囲は、分類器に与えられたタイトル・Abstract・Keywords、およびAbstract欠落時だけの短いIntroduction excerptに固定する。** MethodsやTarget Vulnerabilitiesの肯定ラベルには、Abstract／代用excerpt中の実施・対象の明示が必要。タイトル・Keywordsだけで手法を推定しない。これは「この証拠範囲から支持できるラベル」の評価であり、全文のすべての方法を列挙する評価ではない。

人間が原PDFを読むことは可能だが、評価証拠範囲外にだけ書かれた方法をv1のHuman値へ混ぜない。追加発見は`reviewer_notes`に範囲外として記録し、全文を用いる評価は将来の別条件に分ける。保存された抜粋の欠落・破損などで判断できなければ空欄とUnreviewedを維持する。全文や追加抜粋を外部LLMへ送らない。

## 2. Primary Category

### 共通決定ルール

Primary Categoryは**主要な研究対象または主要貢献が解決するSecurity問題**の単一ラベルである。自動化、分析方式、実験方式はMethodsへ分ける。

1. Abstractの目的・提案・主要結果から「何のSecurity問題を解決／評価するか」を特定する。単なる背景、利用例、将来応用は除く。
2. 下表の6つの対象別Categoryを検討する。対象別の問題が主要貢献なら、自動検出論文でもそのCategoryにする。
3. 特定の対象別Categoryが中心ではなく、脆弱性検査・scanner・診断基盤、または他の脆弱性の検出／評価が中心ならVulnerability Assessmentにする。
4. 上記に該当しないSecurityの主要貢献をOther Securityとする。証拠不足をOther Securityで埋めない。

複数候補の場合は、(a)明示された中心的な研究目的、(b)新規提案が直接改善する対象、(c)主要実験・主要結果の対象、の順に判断する。語の出現回数や固定のCategory優先順位では選ばない。一つを選べる根拠を`reviewer_notes`に記録する。同等の貢献が残り一意に判断できない場合は、Categoryを空欄、Unreviewedとして人間の再確認に回す。

### Category定義・包含・除外・境界

| Category | 定義／含める条件 | 含めない条件 | 境界例とPrimary決定 |
|---|---|---|---|
| Authentication | 本人性・資格情報の検証、ログイン認証ロジックの安全性。Password、MFA、Passkey、WebAuthn、認証プロトコルの性質が中心。 | ログイン後のセッション継続だけの問題、権限判定、アカウント回復、SSO固有フローが中心の場合。 | 認証プロトコルを形式検証する研究は、対象が本人性検証ならAuthentication。Formal Verificationは手法。SSOが一つの適用例で、汎用認証仕様の抽出が主要貢献なら、SSOの登場だけでOAuth / OIDC / SSOにしない。 |
| Session Management | リクエスト間の利用者状態・セッション識別子の生成、継続、更新、失効、保護。Session Fixation、Session Hijacking、SIDの盗用、Cookieによるセッション、Timeout、Logout、Revocationが中心。 | 初回本人確認だけ、オブジェクト権限だけ、JWT形式・署名検証だけ、一般CSRF検査だけの場合。 | Session Fixationの自動検出はSession Management。Automated DetectionやAttack Simulationは手法／Tag。Cookieに格納されたJWTでも、主要貢献がログアウト後のセッション失効ならこのCategory。 |
| Authorization | 誰がどの資源・操作へアクセス可能かという権限判定。Access Control、IDOR、BOLA、水平／垂直権限昇格が中心。 | 本人確認失敗、盗まれたSIDで本人を装うだけ、OAuthという語が登場するだけの場合。 | ログイン済み利用者が他人のオブジェクトへアクセスできる問題はAuthorization。認証手順の欠陥を、結果が不正アクセスという理由だけでAuthorizationにしない。 |
| Token Security | セキュリティトークン自体の生成、署名、検証、保管、漏洩、再利用、失効の性質が中心。JWT、Access Token、Refresh Tokenなど。 | 単にtokenを使用する認証・セッション論文。CSRF tokenが存在するだけ。OAuthフロー固有の関係が中心の場合。 | JWT署名検証の欠陥はToken Security。OAuth redirect／code交換の欠陥はOAuth / OIDC / SSO。SID固定化はSession Management。形式を変えても研究問題が残るか、で対象を確認する。 |
| OAuth / OIDC / SSO | 委任認可・連携認証・SSOに固有のプロトコルフロー、参加者間の信頼、redirect、code交換、IdP／RP間の関係が中心。 | SSOが評価事例の一部に過ぎない汎用認証研究、一般token検証、一般的な資源の権限チェック。 | SSO固有の攻撃フローを検証する研究ならこのCategory。複数のSSOと独自認証への汎用仕様抽出では、主要な問題が連携固有か認証一般かを確認する。 |
| Account Management | アカウント登録、回復、Password Reset、資格情報変更、無効化・削除などのライフサイクル安全性が中心。 | 普通のログイン認証だけ、セッション失効だけ、アカウント乗っ取りが被害として述べられるだけ。 | 回復フローの本人確認不備は、回復設計が主要対象ならAccount Management。MFAの認証強度比較ならAuthentication。 |
| Vulnerability Assessment | 脆弱性の発見・検査・診断・評価を主対象とするscanner／基盤／評価法。または上の対象別6分類に入らない脆弱性の検出・評価。 | Session Fixation等、対象別Categoryの問題が中心で、検査はそのための手段である場合。検査が小さな評価工程に過ぎない場合。 | 汎用web scanner基盤、SQL Injection／CSRFの検出が中心ならこの候補。CSRFとSID管理を一体のセッション安全性として研究する場合は、主要目的と結果でSession Managementとの境界を判断する。 |
| Other Security | 他の7分類に収まらないSecurityの主要研究対象。暗号設計、malware、network securityなど。 | 情報不足、複数候補の未解決、単にSecurityという語がある非Security研究。検査が主要目的ならVulnerability Assessmentを先に検討。 | 暗号方式そのものの設計はこの候補。暗号を用いたweb認証の改善はAuthenticationなど、改善対象で選ぶ。非Security論文は対象外として注記し、8分類へ無理に押し込めない。 |

### 対象と手法の分離例（個別論文のGround Truthではない）

「Session Fixationを自動検出する技術」なら、研究対象はSession Management、直接対象はSession Fixation。自動検出はAutomated DetectionというTagで表せる。攻撃を実行して成否を確認すると明示されていればAttack SimulationというMethodを検討できる。Browser Automationは別の明示証拠が必要である。

CSRFは認証済みブラウザに意図しないリクエストを実行させる攻撃であり、CSRFという名称だけではセッション識別子の奪取やセッション再利用を意味しない。[OWASP CSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)

## 3. Relevance A / B / C

### v1の研究関心と判定手順

中心対象はWeb Session Management、Session Fixation、Session Hijacking。Vulnerability Assessment、Automated Detection、Black-box Testingは、その中心対象の検出・耐性評価を進めるための研究関心として扱う。全Security領域の自動化を同じ強さで関心対象にはしない。

| 値 | 条件 | 記録する根拠 |
|---|---|---|
| A | 主要研究対象／主要貢献がセッションの管理・固定化・窃取・耐性評価へ直接一致する。または、主要貢献がそれらのWeb評価に直接使える汎用の検査・評価方法で、下記のA条件を満たす。 | 対象の直接一致、または具体的な評価手順とそのセッション評価への直接対応。 |
| B | 関連Security分野、または具体的な転用可能性がある検査・分析手法だが、Aの直接一致／直接適用条件を満たさない。 | 関連分野、転用する工程、必要な変更。 |
| C | Security研究だが、主要対象が遠く、セッション安全性やWeb脆弱性評価への具体的な関連・転用工程を説明できない。 | 主要対象と現在の関心との隔たり。 |

**汎用方法をAとするには、次の3条件をすべて満たす。**

1. 主要貢献がWebの脆弱性検査・評価方法そのものである。
2. 評価証拠範囲に、複数利用者／セッション、ログイン前後の状態、SID／Cookie操作、状態遷移、攻撃成功判定など、セッション評価へ直接対応する具体的工程が示される。
3. 対象脆弱性専用のモデルや判定器を新規設計せず、示された工程をセッション検査へ直接使えると説明できる。単に「scannerを拡張できる」「HTTPを送れる」「自動化できる」では不十分。

Aに届かないことだけを理由にCにはしない。具体的な関連・転用があればB。CategoryとRelevanceは独立であり、Vulnerability AssessmentというCategoryでもBになり得る。自動検査、black-box、AIという語だけでAへ上げない。根拠不足とCも区別し、判断不能は空欄にする。

### 境界例

| 研究例 | v1での判定の目安（8本の正解ではない） |
|---|---|
| Session Management | セッション生成・更新・失効などが主要対象ならA。背景説明だけならこの語では決めない。 |
| Session Fixation | 固定化の検出、攻撃成立、防御を主要対象とするならA。別の研究の動機付けで触れるだけならAの根拠にしない。 |
| Session Hijacking | SID／Cookieの窃取・再利用や耐性評価が主要対象ならA。単なる起こり得る被害説明は不十分。 |
| vulnerability scanner一般 | scannerの拡張性、plugin設計、操作負担軽減だけなら通常B。上の3条件を満たす評価方法が主要貢献ならAを検討。対象がWeb／sessionから遠く転用根拠もなければC。 |
| SQL Injection自動検査 | SQLiのpayload探索・攻撃最適化が中心なら通常B。自動化／black-boxというだけでAにしない。主要貢献に上の3条件を満たす汎用評価方法があればAを検討。 |
| CSRF自動検査 | CSRF専用の検出が中心なら通常B。Session Hijackingと同義としてAにしない。主要貢献がセッション安全性の一体評価、または上の3条件を満たす方法ならAを検討。 |
| Authentication protocol verification | Web認証プロトコルの仕様抽出・検証が中心なら通常B。セッションの固定化・継続・窃取耐性が主要検証対象ならAを検討。遠い領域の形式モデルで転用根拠がなければC。 |

## 4. Tags（open vocabulary）

Tagsは複数ラベルで、論文の内容を表す有用な検索語を採用する。語彙は開放するが、証拠のない連想、親概念の自動展開、同義語の重複は採用しない。

| 種類 | 採用条件 | 例／除外条件 |
|---|---|---|
| 研究対象 | 目的・主要貢献・主要評価対象として明示。 | Session Management、Authentication。論文の背景に出るだけでは採用しない。 |
| Security concept | 実際に分析・検査・防御、または重要な攻撃過程として説明される具体的概念。 | Session Fixation、CSRF、Cookie Security。Security、Web Application、Attackなど一般性だけの語は原則除外。 |
| 技術要素 | 提案・解析・実験で実際に重要な役割を持つと明示。 | JWT、Property Graphs、Deep Q-learning。Abstractに出るだけの比較例・関連研究は除外。 |
| Tool / mechanism | 提案・実使用のtool名や機構。 | Deemon、AUTHSCAN、Automated Detection、Vulnerability Scanner。既存toolの紹介だけでは採用しない。 |

親概念は「その概念自体が主要対象である」という独立の根拠がある場合に限る。例えばSession FixationとSession Managementを併記できる場合はあるが、Session FixationからSession Hijacking、Account Takeover、Broken Access Controlを機械的に追加しない。

Session Fixation論文へのSession Hijacking Tagは、窃取／再利用の攻撃過程が実質的に分析・検証される場合にのみ検討する。「結果として乗っ取り得る」という背景説明だけなら付けない。CSRF論文にも、別途Session Hijackingを実質的に扱う明示証拠がある場合だけ付ける。

TagsはTarget Vulnerabilitiesより広い。重要な技術・攻撃過程をTagとして認めても、直接対象の脆弱性とは限らない。同じ語を複数欄に入れる場合は、各欄の条件をそれぞれ満たすことを確認する。

AIの過剰な一般概念は、(1)主題への貢献、(2)具体性、(3)明示証拠、(4)既存Tagとの独立性で判断する。Human値はAIのラベル集合から選び直す方式にせず、独立に作成する。将来のmulti-label評価では根拠のない一般概念もFalse Positiveとして残し、正規化で削除して救済しない。

## 5. Research Methods

Methodsは「研究をどう実施したか」を表す。推奨13語は排他的ではないが、各ラベルに独立した実施証拠が必要。自動的な親ラベル追加はしない。

| Method | 簡潔な判定基準 | この情報だけでは付けない |
|---|---|---|
| Black-box Testing | 対象のソースや内部計装を使わず、外部入出力・応答・観測可能な状態で検査することを明示。 | Web対象、HTTP送信、自動検査、専用環境不要という語だけ。 |
| White-box Testing | ソース、内部構造、内部実行情報を検査設計・判定に利用すると明示。 | open-source製品を実験対象にしただけ。 |
| Static Analysis | 対象を実行せず、コード／構造／モデルを解析すると明示。 | graphを使うだけ。動的traceから作ったgraphを扱うだけでは追加しない。 |
| Dynamic Analysis | 対象を実行し、runtime trace、data flow、状態や応答を解析すると明示。 | toolを動かした、実験した、scannerと呼ぶだけ。 |
| Browser Automation | browserによるnavigation、操作、Cookie操作などをプログラムが自動実行すると明示。 | ブラウザ、拡張機能、Cookie、HTTP clientの利用だけ。手動操作か不明なら付けない。 |
| Attack Simulation | 具体的な攻撃手順を再現し、攻撃成立／防御成否を観測すると明示。実攻撃の制御された再現を含む。 | 攻撃を背景説明するだけ、脆弱な候補を列挙するだけ。 |
| Measurement Study | 実サービス等の集合について、安全性・設定・頻度などを系統的に測定・比較すると明示。 | 製品数が多いだけ、単なる提案手法の試験だけ。 |
| Formal Verification | 形式仕様・モデルに対してSecurity性質を検証すると明示。 | 理論的、仕様抽出、graph traversalという語だけ。検証toolを実際に使用するか確認。 |
| Machine Learning | 学習データ／経験でモデル・policyを学習し、研究に使用すると明示。 | AIという名称、heuristic、ルールベース検出だけ。 |
| Survey | 既存研究・技術を系統的に収集・整理・比較することが主要研究方法。 | 通常のRelated Workや導入文だけ。 |
| Tool Development | 提案を実装したtool／prototype／frameworkの開発が研究成果として明示。 | 既存toolを使っただけ、未実装の構想だけ。 |
| Experimental Study | testcase、攻撃条件、設定などを意図的に操作し、その結果で提案・仮説を検証すると明示。 | 「評価した」の一語、既存観測データの分析だけ。 |
| Empirical Study | 実サービス、実利用、実験・観測データなどを系統的に分析して知見を得ることが研究方法として明示。 | 多くの研究が実証的であるという一般推論だけ。 |

### 特に混同しやすい6語

- **Browser Automation**は実行手段。自動HTTP送信と同一ではなく、Black-box Testingの必要条件でもない。
- **Attack Simulation**は攻撃再現の設計。手動でも成立し、browser自動化やソース非使用は含意しない。
- **Tool Development**は実装成果。利用toolがあるというだけでは足りず、Black-box／Dynamicも含意しない。
- **Experimental Study**は評価設計。条件と成否・測定結果が示されているか確認する。
- **Dynamic Analysis**は実行時情報の解析。内部traceを使う場合もあるため、Black-boxと自動併記しない。
- **Black-box Testing**は対象内部へのアクセスの前提。browserや攻撃再現の有無とは別に判定する。

例として「browserを自動操作し、ソースを参照せず、固定化攻撃を実行し、応答から成否を分析し、条件を変えて検証し、新toolを実装した」と明示されれば、複数Methodが成立し得る。いずれか一つが明示されたことから残りを推測しない。

Automated DetectionとVulnerability Scannerは目的／toolの性格としてTagsで扱い、v1のMethodsには採用しない。自動化の具体的実施方法が書かれていれば該当するMethodを別途判断する。AI原値のこれらの語は書き換えない。

推奨語以外も、固有の研究方法が明示されていれば採用可能。Reinforcement Learningはその例で、Machine Learningへの正規化置換や自動的な併記はしない。汎用語と具体語の両方を付けるには、それぞれの実質的な説明を必要とする。将来の比較では推奨語限定とopen vocabularyを混在させず、評価語彙の条件を明記する。

Abstract（欠落時のexcerpt）にないMethodを、tool名、AI理由、他論文の知識から推測してGround Truthへ追加しない。明示根拠が支持するラベルだけを確定する。証拠範囲を正常に確認した結果、支持できるMethodがない場合は`[]`。抽出欠落等で確認できない場合は空欄にする。

## 6. Target Vulnerabilities

**論文が直接検出・評価・攻撃・防御対象とする具体的な脆弱性／攻撃クラスだけ**を採用する。フィールド名はVulnerabilitiesだが、明示されたSession Hijackingのような攻撃クラスも直接対象なら含める。

採用には次の両方が必要である。

1. Abstract／代用excerptに具体的な対象名または明確な機構が示される。
2. その対象を提案手法・検査・評価・攻撃・防御が直接扱うと明示される。

背景、Related Work、動機付け、比較の紹介、将来的な対応、被害／結果、関連概念は除く。一般的なWeb Application Vulnerabilities、Security、Access Controlは具体的対象の代用品にしない。Broken Access Controlのような広い名称も、そのクラス自体を直接評価すると明示された場合に限る。

| 境界 | v1の扱い |
|---|---|
| Session Fixation → Session Hijackingという結果 | Fixationが直接対象ならその候補を判断する。Hijackingが固定化攻撃の成功説明だけなら、独立のTarget Vulnerabilityとして追加しない。 |
| Session Hijacking自体の耐性評価 | 盗んだSID／Cookieの再利用、binding、失効などを直接試験するなら、その攻撃クラスを対象として検討する。 |
| CSRF → Account Takeoverという被害 | CSRFの検査だけなら、被害からSession HijackingやAccount Managementへ対象を拡張しない。 |
| AUTHSCANとIDOR / BOLA | 認証仕様抽出や「7 vulnerabilities」の記載だけでは根拠にならない。具体的なオブジェクト権限チェックの欠陥が直接検査対象として示されるか確認する。 |
| IDOR / BOLA / Broken Access Control | 関連する語でも同義語置換・親子展開をしない。それぞれが直接対象である証拠がある場合だけ併記。 |
| scanner一般で具体的対象なし | 評価証拠範囲を確認して具体的ラベルが支持されなければ`[]`。対象を推測して埋めない。 |

Session FixationからHijackingが生じ得ることと、評価用ラベルを両方付けることは別の判断である。[OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)

BOLAはオブジェクト単位の権限確認の問題であり、認証一般の説明からは推定できない。[OWASP API1:2023 BOLA](https://api-security.owasp.org/editions/2023/en/0xa1-broken-object-level-authorization/)

## 7. Normalization v1

Versionは`normalization-v1`。以下の辞書と手順を本書で固定し、将来の実装の仕様とする。今回、正規化コードやデータの書換えは行わない。

### 明示的な同義語辞書

| 適用フィールド | 入力（大小文字を問わない） | 評価用canonical値 |
|---|---|---|
| Tags / Target Vulnerabilities | CSRF; Cross Site Request Forgery; Cross-Site Request Forgery; Cross Site Request Forgery (CSRF); Cross-Site Request Forgery (CSRF) | `CSRF` |
| Tags / Target Vulnerabilities | SQLi; SQL Injection | `SQL Injection` |
| Tags / Methods | Black box testing; Black-box Testing; Black Box Testing | `Black-box Testing` |

現在保存されている`Cross-Site Request Forgery (CSRF)`も明示的に辞書へ含める。句の部分一致、自由な略語展開、編集距離による近似一致は使用しない。例えば`Login CSRF`を`CSRF`へ潰さない。

### 評価時の手順

1. 空欄と`[]`を先に区別する。空欄はmissing、`[]`は確認済み空集合として維持する。
2. multi-label値は文字列のJSON配列として検証する。配列以外、文字列以外の要素、空文字要素は不正値としてレビューへ返す。
3. 各ラベルの前後空白を取り、連続する空白を一つにする。辞書のlookupだけ大小文字を区別しない。
4. フィールド別辞書に完全一致するラベルをcanonical値に置換する。未登録語の表記は、空白整理以外維持する。全語を一律小文字化しない。
5. canonical値の完全一致だけ重複排除し、集合として比較する。表示順は採点に影響しない。
6. AIとHumanの両方に同じ版を適用する。派生値に元レコード識別子、元フィールド、`rubric_version=v1`、`normalization_version=normalization-v1`を紐付ける。

派生値の概念例は`normalized_ai_tags`と`normalized_ground_truth_tags`。将来の評価出力内で生成し、AI原値、分類履歴、Human原値を上書きしない。既存CSVの版列は人間がレビュー完了時に記録する。この文書作成時には埋めない。

### 統合しないもの

- Session Fixation / Session Hijacking
- IDOR / BOLA（Broken Access Controlへの展開も行わない）
- Machine Learning / Reinforcement Learning
- Authentication / Authorization

親概念・子概念、原因・結果、研究対象・手法は同義語ではない。正規化は誤分類や過剰ラベルを消す処理にしない。未知語や不正値は黙って除去しない。

Primary CategoryとRelevanceは列挙値の前後空白だけを取り、正確な8分類／A・B・Cへ検証する。別Categoryへの推測置換はしない。辞書を変える場合は新しいnormalization版とし、両側・全対象へ再適用して旧結果と区別する。

## 8. Confidence

`ai_relevance_confidence`はLLMが自己申告した補助値であり、実測Accuracyでも校正済み確率でもない。現在の8件はすべて`0.95`だが、それだけでは正誤も信頼性も判定できない。

- Ground Truth判定、review_status、評価対象の採否に使用しない。
- Correct / Incorrectの代わりにしない。Accuracyの分母や重みに使わない。
- AI原値として保存し、勝手な修正・補完・Human confidenceへの転記をしない。
- 将来の校正評価は十分な独立Humanラベルが得られた後の別分析。全件同値なら、その値による順位付けの情報もない。

## 9. Ground Truth入力ルール

### 空欄と確認済み空集合

| 値 | 意味 |
|---|---|
| 空欄（CSVの空セル／xlsxの空セル） | 未レビュー、未確定、または証拠不足で判断を保留。AI値へのfallbackをGround Truthとして採用しない。 |
| `[]` | 人間がv1の証拠範囲を確認し、このフィールドに支持できるラベルがないと確定したJSON空配列。 |
| `["CSRF"]`など | 人間が確定した文字列のJSON配列。自由なカンマ区切りやPythonリスト表記は使用しない。 |

`[]`はTags / Methods / Target Vulnerabilitiesのみに使う。CategoryとRelevanceには必ず有効な単一ラベルが必要。抽出失敗・未読・判断不能を`[]`に変換しない。`[]`は全文にも該当方法／対象が存在しないと断言する値ではない。

### Reviewedの必須条件

`human-ground-truth.xlsx`と`data/ground_truth.local.csv`には同じ論理ルールを適用する。以下のHuman項目をすべて確定し、人間が明示的に完了操作した行だけ`Reviewed`にする。

| 項目 | 必須条件 |
|---|---|
| `ground_truth_category` | 定義された8分類の一つ。 |
| `ground_truth_relevance` | `A` / `B` / `C`の一つ。 |
| `ground_truth_tags` | 非空セルの有効なJSON文字列配列。確認済みなら`[]`も可。 |
| `ground_truth_methods` | 同上。各肯定ラベルに明示実施証拠がある。 |
| `ground_truth_target_vulnerabilities` | 同上。各肯定ラベルが直接対象である。 |
| `reviewer_notes` | Categoryの主要対象とRelevanceの判断理由を短く記録。境界判断、除外理由、確認済み空集合の理由も該当時に記録。 |
| `evidence_reference` | `abstract: 目的文／提案文`、`introduction_excerpt: Cookie操作の説明`など証拠位置。各肯定Method／Targetを辿れるようにする。 |
| `reviewer_id` | 人間のreviewerを識別する非空値。 |
| `reviewed_at` | timezone付きISO 8601のレビュー完了日時。 |
| `rubric_version` | `v1`。 |
| `normalization_version` | `normalization-v1`。 |

`review_status`は`Unreviewed` / `Reviewed`のみ。部分入力があっても未確定項目が一つでもあればUnreviewed。値がすべて埋まっていても自動でReviewedにしない。後で判断を保留する場合は人間がUnreviewedへ戻し、理由を残す。`file_hash`による行の同一性、AI列、provider/model、classification_run_idなど元Predictionへの対応は維持する。

この完了条件は**評価フォーマットの仕様**であり、既存UIの`manually_reviewed`の検証実装がすべてを強制するという意味ではない。今回UI保存やCSV／xlsx／DBの同期は行わない。将来の入力時は両形式に食い違いがあれば人間が解消するまで評価から除外し、AI列を同期のために書き換えない。

今回確認したCSVは8行、全Humanラベル空欄、全件Unreviewed。`human-ground-truth.xlsx`はproject内で確認できていないため、実際のsheet構成や入力検証を確認したとは扱わない。

## 10. Evaluation metricsと既存コードとの接続

### v0.1.1の中心評価

人間が上の条件でReviewedにした行のうち、有効なPrimary Categoryと対応する保存済みAI Predictionがある行を評価する。PDF hashごとに1行とし、provider/modelとclassification_run_idでPredictionを固定する。再試行・重複行で分母を増やさない。

| Metric | 定義 |
|---|---|
| Accuracy | Category完全一致件数 / 評価件数N。 |
| per-class Precision | `TP_c / (TP_c + FP_c)`。そのクラスを予測したうち正しい割合。 |
| per-class Recall | `TP_c / (TP_c + FN_c)`。Humanがそのクラスとしたうち正しく予測した割合。 |
| per-class F1 | `2PR / (P + R)`。 |
| support | Humanがクラスcとした件数`TP_c + FN_c`。 |

AccuracyのN=0は未定義（既存コードの`None`）。ゼロ除算になるクラスのPrecision／Recall／F1は、既存コードに合わせ0で出すが、supportや予測件数が0であることを併記し、クラス性能が観測されたと解釈しない。全8分類を表示する場合、未出現クラスのsupport=0は「性能未評価」を意味する。

必ずN、全対象8本のうちのreview coverage、除外件数と理由、Human class distribution、provider/model、Predictionの固定条件、rubric版、normalization版を併記する。8本だけの値は予備的評価であり、クラスのsupport不足も報告する。現時点はReviewed=0なのでAccuracyやF1を計算・推定しない。

### 既存コードでできること／まだ強制されないこと

`scripts/evaluate.py`は既に`ground_truth_category`と`ai_primary_category`のCSVから、Accuracy・クラス別Precision／Recall／F1・supportを計算できる。ただし**CSV経路はreview_status、他のHuman項目、版、列挙値、重複を検証せず、両Categoryが非空の行を採用する**。出力クラスもHuman／AIに出現するクラスの和集合であり、常に8分類を表示するわけではない。

将来の実行前に、本書のReviewed条件を満たす行だけを人間が確認したローカル評価用CSVへ選別し、版とPrediction条件を記録する。未完了の`ground_truth.local.csv`をそのまま採点に渡さない。今回は選別ファイルを作成しない。

DB経路は`manually_reviewed=1`の現在Categoryと成功した分類履歴を読み、provider/modelごとの最新成功をhash単位で使う。CSVの`review_status`や版列とは連動せず、今回の固定runと一致するとも限らない。CSVの入力をDBへ書き込まない。今回の8本は保存済みrunを固定したCSV経路を想定し、現コードで対応済みのCategory指標を利用する。コードの拡張は今回行わない。

### Ground Truth完成後の次段階

- Tags / Methods / Target Vulnerabilities: フィールドごとに正規化済み集合のmicro／macro Precision・Recall・F1、per-label supportを追加。必要に応じexact-set matchやJaccardも併記する。空欄を空集合扱いしない。双方`[]`の場合、個別P/R/F1は未定義として別集計し、exact-set matchは一致とする。
- Relevance: A/B/C完全一致率と3×3 Confusion Matrix（行Human、列AI）、各クラスsupportを追加。Categoryと分けて評価する。
- Confidence: Ground Truth完成後の別分析として扱う。自己申告値とAccuracyを同じ指標として報告しない。

multi-labelで不正値／未知語を黙って捨てない。追加の同義語統合が必要ならnormalizationを版更新し、全対象に同じ処理を適用する。

## 11. 8本のHuman Review Checklist

以下は保存済みのタイトルとAbstract（1本はIntroduction excerpt）、AI出力の確認から作成した**質問だけ**である。Category／Relevance／ラベルの正解は記入していない。表示順は既存ローカルCSVの行順。

### 全8本共通

- [ ] AI列を非表示にして独立判断を始めたか。
- [ ] 主要対象・主要貢献・Methodsを別々に整理したか。
- [ ] 全件Relevance AというAI結果に引きずられず、Aの直接一致条件／汎用方法の3条件、Bの転用理由、Cの弱い関連を確認したか。
- [ ] 全件Confidence 0.95を判断根拠・正誤・レビュー完了の根拠にしていないか。
- [ ] Browser Automationについて「browser操作の自動実行」の明示があるか。Cookie・browser拡張・HTTP送信だけで追加していないか。
- [ ] Session Hijackingは主要対象、実質的なTag、直接Target、結果説明のどれかを分けたか。
- [ ] Categoryは単一、Methods／Targetsは根拠あり、空欄と`[]`は区別され、review evidenceと版を記録したか。

### 1. AUTHSCAN: Automatic Extraction of Web Authentication Protocols from Implementations

- [ ] 中心的貢献は認証仕様の自動抽出か、SSO固有の安全性か、汎用脆弱性検査基盤か。Authentication／OAuth / OIDC / SSO／Vulnerability Assessmentの境界を目的と主要結果で確認したか。
- [ ] AIのIDOR / BOLA / Broken Access Controlに、それぞれ直接の対象証拠があるか。「7 vulnerabilities」だけで種類を推定していないか。
- [ ] off-the-shelf verification toolsを用いた検証は証拠範囲に明示されるか。仕様抽出とFormal Verificationを区別したか。
- [ ] Black-box Testingの内部アクセス前提は明示されるか。Automated Detection／Vulnerability ScannerをMethodとして機械的に採用していないか。
- [ ] 認証プロトコルの安全性とセッション安全性を同一視せず、Relevanceの直接一致または転用工程を説明できるか。

### 2. Deemon: Detecting CSRF with Dynamic Analysis and Property Graphs

- [ ] CSRF検査が中心か、セッション管理そのものが中心か。タイトル中の検査手法と研究対象を分けたか。
- [ ] dynamic traces／property graph／security testsのうち、各Methodの実施証拠を確認したか。open-source評価対象だけからWhite-box、graphだけからStatic Analysisを推定していないか。
- [ ] AIのBrowser AutomationはAbstractに明示されるか。automatically conducts testsとbrowser自動操作を混同していないか。
- [ ] XSS／SQLiは比較・背景か直接対象か。Account Takeoverという結果からSession Hijackingを追加していないか。
- [ ] CSRF専用検出のRelevanceとセッションへの直接適用を区別したか。`Cross-Site Request Forgery (CSRF)`の派生値を`CSRF`へ正規化する条件を確認したか。

### 3. Automated Detection of Session Fixation Vulnerabilities

- [ ] 固定化が主要対象か、検査一般が主要貢献かを明示し、対象Categoryと自動化Methodを分けたか。
- [ ] attack simulatorによる実攻撃・成否確認の記述を確認したか。Browser AutomationやBlack-box Testingには別の証拠があるか。
- [ ] AIのSession Hijackingは固定化の結果説明か、独立した直接検査対象か。TagsとTarget Vulnerabilitiesで別々に判断したか。
- [ ] original test cases／real-world applicationの実験記述から、どのMethodの条件が明示されるか確認したか。
- [ ] Relevanceは自動化という語ではなく、主要対象・貢献に基づいて独立に判断したか。

### 4. Amberate: Webアプリケーションの脆弱性自動検出フレームワーク

- [ ] 中心的貢献はscanner拡張の負担軽減・設計か、特定セッション脆弱性の検査か。
- [ ] 一般scannerのRelevanceについて、Aの3条件を満たす具体的工程があるか。拡張可能性だけからセッションへの直接一致を主張していないか。
- [ ] 「既存scannerのソース変更負担」は対象webアプリのソース非使用を意味するか。Black-box Testingの根拠を取り違えていないか。
- [ ] Browser Automationの明示はあるか。frameworkのdesignと、実装済みTool Developmentの証拠を分けたか。
- [ ] AIのWeb Application Vulnerabilitiesは具体的な直接Targetか、対象全般の名称か。具体的対象が支持されない場合の`[]`条件を確認したか。

### 5. Automatically Checking for Session Management Vulnerabilities in Web Applications

- [ ] 主要目的はセッション安全性の一体的評価か、CSRF単独検査か。複数対象時のPrimaryルールを適用したか。
- [ ] Session FixationとCSRFについて、背景説明だけでなく提案検査の直接対象として明示されるか。
- [ ] Session Hijackingは独立した検査対象か、固定化／CSRFの結果として用いられる表現か。
- [ ] simulating real attacksの実施、Black-boxの前提、Browser Automationをそれぞれ別に確認したか。「専用環境不要」だけで前提を推定していないか。
- [ ] 自作アプリ・7実サービスの実験で支持されるMethodと、`Cross Site Request Forgery`のCSRF正規化を確認したか。

### 6. Web サービスのセッション窃取攻撃耐性の評価

- [ ] Abstract欠落によるIntroduction excerptの使用を明記したか。根拠がこの範囲にあるか確認したか。
- [ ] 主要対象は認証強度か、認証後のCookie／SIDの窃取耐性か。MFAという背景語だけでCategoryを選んでいないか。
- [ ] browser拡張によるCookie／User-Agent操作は手動か自動か明示されるか。Browser Automationを推定していないか。
- [ ] 窃取・再利用とSession Fixationの機構を区別したか。AIのSession Fixationに直接対象の証拠があるか。
- [ ] Fingerprint／SID寿命は既存対策の背景か、実際に比較・評価した対象か。Measurement Study、Attack Simulation等は各判定基準に届くか。

### 7. ウェブアプリケーションにおけるセッション固定化脆弱性の検出支援

- [ ] 検出の研究対象と実装toolの貢献を分け、Categoryを対象から判断したか。
- [ ] Session Fixationと、SID取得後のアカウント乗っ取りという結果説明を区別したか。Session HijackingをTag／Targetに含める独立証拠があるか。
- [ ] implemented a toolの明示と、Browser Automation／Black-box Testing／Attack Simulationの実施証拠を別々に確認したか。
- [ ] AIのAutomated DetectionをMethodとして受け継がず、具体的な実施方法だけを判定したか。
- [ ] Relevanceの根拠を主要対象から記録し、AI理由を証拠として転記していないか。

### 8. 深層強化学習を用いたWebアプリの脆弱性検査のためのAIエージェント

- [ ] 主要対象はSQL Injectionの攻撃・検査か、汎用検査方法か。Machine LearningというMethodでCategoryを決めていないか。
- [ ] Relevanceについて、SQLi専用payload最適化と、セッションへ直接使える検査工程を分けたか。自動検査だけでAにしていないか。
- [ ] Reinforcement Learning／Deep Q-learningの明示を確認し、Machine Learningへの同義語統合や自動的な親ラベル追加をしていないか。
- [ ] HTTP requestsの送信だけからBrowser Automationを付けていないか。Black-boxの前提とCTF環境による実験・攻撃再現を別々に判定したか。
- [ ] SQL Injectionが直接対象かを確認したか。OWASP ZAP／Burp Suiteは背景の紹介か実使用かを分け、Tagを過剰追加していないか。

## 12. この文書作成時の変更境界

作成物は本書のみ。Human Ground Truth、Human correction、review_status、版列、AI原値、分類履歴、Confidence、PDFには書込みをしない。再分類、Prompt変更、commit、mainへのmerge、v0.1.1 tag作成、remote追加、pushは行わない。

保存構造・データフロー・実行時動作は変更しないため、今回はarchitecture文書や評価コードの変更対象を増やさない。本書の正規化・完了条件・将来指標は仕様であり、実装済みの機能と区別する。
