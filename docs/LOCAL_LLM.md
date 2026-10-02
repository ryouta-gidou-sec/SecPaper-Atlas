# Local LLM Setup

## v0.1.1で使用した構成

SecPaper Atlasのデフォルトproviderは`local`。v0.1.1の8論文の評価では、Ollama `0.35.0`と`qwen3:4b`（Q4_K_M）を使用した。これは評価時の記録であり、最新版の指定や他環境での性能保証ではない。結果と限界は[Evaluation Results](EVALUATION_RESULTS.md)を参照。

## Windows / PowerShell

1. [公式Windows版Ollama](https://ollama.com/download/windows)をインストールする。導入条件は[Windows documentation](https://docs.ollama.com/windows)を参照。アプリ自身はOllamaの導入やモデル取得を行わない。
2. タスクトレイからOllamaを終了する。Windowsのユーザー環境変数に`OLLAMA_NO_CLOUD=1`、`OLLAMA_HOST=127.0.0.1:11434`を設定し、スタートメニューからOllamaを起動する。[公式FAQ](https://docs.ollama.com/faq#setting-environment-variables-on-windows)に設定手順がある。cloud無効化後はOllamaログの`Ollama cloud disabled: true`で確認できる。
3. 新しいPowerShellでモデルを明示的に取得し、インストール済み一覧を確認する。

   ```powershell
   ollama pull qwen3:4b
   ollama list
   ```

4. プロジェクトのルートで、`.env.example`から未作成の`.env`を用意する。既存の私的設定を上書きしない。

   ```powershell
   if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
   ```

5. `.env`の分類設定を確認する。

   ```dotenv
   CLASSIFIER_PROVIDER=local
   LOCAL_LLM_MODEL=qwen3:4b
   LOCAL_LLM_BASE_URL=http://127.0.0.1:11434
   LOCAL_LLM_TIMEOUT=180
   LOCAL_LLM_VALIDATION_RETRIES=1
   ```

6. Python環境と依存関係を[READMEのSetup](../README.md#setup)に従って用意し、ルートから起動する。

   ```powershell
   .\.venv\Scripts\python.exe -m streamlit run app.py
   ```

モデル名にコード上のデフォルトはない。使用するインストール済みモデルを明示する。処理時間や必要なメモリはモデル・CPU/GPU・入力長・他のアプリに依存する。

## Classification contract

Ollama `/api/chat`へ共通JSON Schemaを渡し、JSONをPydanticで厳密に検証する。`qwen3:4b`の呼出しは`think=false`、`temperature=0`、`num_ctx=8192`、`num_predict=1024`を使用する。構造の検証は意味的な分類精度を保証しない。

不正なJSON/schemaでは最大1回だけ再生成する。接続・timeout・未取得モデル・HTTPエラーはその処理内で再試行しない。ローカルmodeからOpenAIへ自動的に切り替えない。

## Privacy boundary

論文入力は信頼するローカルOllamaへだけ送信する。アプリはHTTP loopback以外のendpoint、URL内のcredentials、redirect、cloud model参照を拒否し、proxy設定を使用せず、入力送信前にインストール済みモデルのメタデータを確認する。

`OLLAMA_NO_CLOUD=1`はOllamaサーバー側の設定。[cloud無効化の公式手順](https://docs.ollama.com/faq#how-do-i-disable-ollama-cloud-features)に従って変更後に再起動する。アプリの`.env`へ書くだけでは起動済みサーバーを変更できない。ソフトウェア導入・モデル取得・更新は別途ネットワークを使用する。

## Troubleshooting

- **pending:** `CLASSIFIER_PROVIDER`と`LOCAL_LLM_MODEL`の設定を確認する。
- **Connection error:** Ollamaが起動し、設定したloopback endpointで待ち受けているか確認する。
- **Model not installed:** `ollama list`と`.env`のモデル名を照合する。取得は上記のコマンドで利用者が行う。
- **Timeout:** 実行環境を確認し、必要なら`LOCAL_LLM_TIMEOUT`を1〜600秒の範囲で調整する。
- **needs_review:** タイトル・Abstractまたは代用excerptの抽出品質に問題があるため、LLM送信前に保留された状態。

再スキャンはpending / failed / needs_reviewを再試行する。分類済みhashはスキップし、元PDF・既存のHuman Review値・過去のAI分類履歴を保持する。
