# Local Ollama setup proposal

## Current PC and candidate models

Inspected on 2026-10-01: Intel Core i7-1255U, about 16GB RAM, Intel Iris Xe integrated graphics. Ollama was not found in PATH, standard install locations or running processes. CPU inference is the conservative starting point; no dedicated GPU/VRAM is required for it.

| Model | Download | Planning estimate for model RAM at context 8192 | Recommendation |
|---|---:|---:|---|
| qwen3:4b (Q4_K_M) | 2.5GB | about 4–6GB, plus Windows/app memory | First candidate on this 16GB PC |
| qwen3:8b (Q4_K_M) | 5.2GB | about 8–10GB, plus Windows/app memory | Later quality comparison; slower and less memory headroom |

Downloads are listed by the official [4b](https://ollama.com/library/qwen3:4b) and [8b](https://ollama.com/library/qwen3:8b) pages. RAM figures are planning estimates, not vendor guarantees or measured performance. CPU speed, context and other running apps affect feasibility. Prefer 16GB system RAM for the first candidate; a dedicated GPU is optional. Classification accuracy and latency on the eight real PDFs remain unmeasured until installation is approved.

[Qwen3](https://qwenlm.github.io/blog/qwen3/) supports Japanese and English, instruction following and non-thinking inference. Both candidates use Apache 2.0, also shown by the official [model card](https://huggingface.co/Qwen/Qwen3-4B). The license permits commercial use subject to its terms, including license/notice obligations when redistributing. Ollama uses the [MIT license](https://github.com/ollama/ollama/blob/main/LICENSE). These are candidates for portfolio use; schema compliance does not establish classification quality.

## Installation approval boundary

No installation or model download has been performed. Official Ollama release metadata currently lists [v0.35.0](https://github.com/ollama/ollama/releases/tag/v0.35.0), with OllamaSetup.exe at 1,571,105,888 bytes (about 1.57GB). Versions and installer sizes change. The [Windows documentation](https://docs.ollama.com/windows) requires at least 4GB for the binary installation, separately from model storage. Reserve roughly 10GB of free disk space for installation, installer and the first model.

After approval:

1. Install the official Windows Ollama release as a normal user.
2. Configure the Ollama server process with `OLLAMA_NO_CLOUD=1` and restart it. This is a server setting, not merely an app .env setting. Confirm cloud is disabled and the server listens on loopback.
3. Explicitly download only the chosen model, for example `ollama pull qwen3:4b`. The app never downloads models.
4. Add CLASSIFIER_PROVIDER=local and LOCAL_LLM_MODEL=qwen3:4b to the existing ignored .env, preserving secrets. Keep LOCAL_LLM_BASE_URL=http://127.0.0.1:11434.
5. Confirm the locally installed model using Ollama metadata before sending paper input.
6. Hash all eight immutable PDFs, scan failed/pending rows once, then verify JSON/Pydantic validation, unique DB records, provider/model/time, Streamlit filters/details, untouched human fields and final PDF hashes.

The app uses [Ollama JSON Schema structured outputs](https://docs.ollama.com/capabilities/structured-outputs). Invalid output permits at most one regeneration; connection and model errors fail without retry. If CPU classification times out, adjust LOCAL_LLM_TIMEOUT within 1–600 seconds after inspecting the failure rather than repeatedly resubmitting the inbox. Local mode never falls back to OpenAI.

Model downloads and software updates access the network separately. Local Providerでは論文情報がPC外へ送信されない: paper input goes only to the trusted local Ollama installation; remote/cloud model references, external endpoints, proxies and redirects are rejected. OpenAI receives input only when the user explicitly selects the OpenAI Provider.
