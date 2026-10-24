# AI News Reporter — Anna Executa plugin

Anna "Tool" wrapper for [ai_news_reporter](https://github.com/Ephigma/ai_news_reporter).
The original repository is not changed or required.

## What it does

| Tool | What it does | LLM used? |
|---|---|---|
| `search_ai_news` | Searches recent AI news (Tavily) and removes duplicates | No |
| `ai_news_report` | Same, then writes a markdown report (summary + highlights + links) | Yes, Anna's LLM (sampling) |

## Security design

- **Standard library only**: no third-party packages, nothing extra to trust.
- **Only one secret**: the user's own `TAVILY_API_KEY`, injected by Anna per request.
  It is never logged, returned, cached or written to disk.
- **No OpenAI / Anthropic keys**: summaries use Anna sampling (billed to the user's Anna credits).
- **Network**: only `https://api.tavily.com`. No web scraping.
- **Prompt-injection guard**: article text is marked as untrusted in the LLM prompt.
- **No disk writes, no shell commands.**

## Test locally

```bash
python3 tests/test_plugin.py      # fake Anna host + fake Tavily, no key needed
echo '{"jsonrpc":"2.0","method":"describe","id":1}' | python3 src/anna_ai_news_reporter/plugin.py
```

## Install / publish

```bash
uv tool install .          # entry point: anna-ai-news-reporter
```

Then register it as an Executa in the Anna Developer Console (distribution `uv`),
and add it as a required Executa of the "AI News Reporter" app.
