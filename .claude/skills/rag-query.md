# Skill: rag-query

Run a RAG (Retrieval-Augmented Generation) query using the Jetson Orin Nano GPU, via a direct
HTTP call to whichever `llama-server` instance is loaded with the right GGUF for the task.

## Usage

```
/project:rag-query QUERY [--context products|styles|both] [--url URL]
```

- `QUERY` — natural language question or task
- `--context products` — retrieve from `state/products.json` (catalog, prices, descriptions)
- `--context styles` — retrieve from `config/writing_styles.yaml` (voice, tone, prompt examples)
- `--context both` — (default) combine both sources
- `--url` — override the llama-server base URL (default: `LLM_TEXT_URL` from `.env`)

## Steps

1. Load the requested context source(s) into a context window.
2. `POST {url}/v1/chat/completions` (OpenAI-compatible) with the query + context as the user
   message — e.g. `curl {LLM_TEXT_URL}/v1/chat/completions -d '{"messages":[...]}'`.
3. Return the synthesized answer.

## Jetson GGUF model constraint

llama.cpp's `llama-server` serves **one model per process** — unlike Ollama it cannot hot-swap
models on demand. Each of the tasks below needs its own `llama-server` instance/port running
concurrently on the Jetson, so plan port allocation (and RAM — the Jetson has 8 GB total) before
loading more than two or three GGUFs at once.

| Task | Suggested GGUF | Typical port |
|---|---|---|
| EN/RU/HE translation | aya-8b GGUF | (assign per deployment) |
| Structured product data extraction | qwen3-coder GGUF | (assign per deployment) |
| Fast Q&A over catalog | llama-3.2 GGUF | (assign per deployment) |
| Style-aware copywriting / general RAG synthesis | mistral-7b-instruct or qwen2.5-7b-instruct GGUF | `LLM_TEXT_URL` (8002) |
| Vision over product images | llava-phi3 GGUF (with `--mmproj`) | `LLM_VISION_URL` (8001) |

## RAG Patterns for This Project

**Find similar products:**
> "Which products in the catalog are most similar to a blue oval bowl priced at 180 ILS?"

**Style-guided generation:**
> "Write a Facebook post for product 20260215_200 following Lika Val's voice from writing_styles.yaml"

**Batch translation check:**
> "List all products where the RU title is missing or empty"

**Etsy listing review:**
> "Review the Etsy listing for 20260215_200 against Etsy SEO best practices"

## Notes

- The Jetson host is configured via `LLM_VISION_URL`/`LLM_TEXT_URL` in `.env` (see `config/config.yaml`'s `llm:` block) — must be on the same local network (LAN).
- For large batch jobs, prefer a 7B-class GGUF over 30B to avoid OOM on 8 GB Jetson RAM.
- Embeddings for semantic search: run a dedicated `llama-server --embedding` instance and call its `/v1/embeddings` endpoint.
