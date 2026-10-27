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

## Project layout

This repo is an Anna App with one bundled Tool Executa. The handle
`ai-news-reporter` ties the files together; `anna-app apps publish` resolves it to
the platform-assigned tool id.

```
app.json                      bundled_executas["ai-news-reporter"].path ─┐
manifest.json                 required_executas: bundled:ai-news-reporter │
executas/ai-news-reporter/  ◄─────────────────────────────────────────────┘
├── executa.json              distribution: active "binary", 4 platform archives
├── manifest.json             describe output, synced to the server on publish
│                             (generated: scripts/build_binary.py --write-manifest)
├── ai_news_reporter_plugin.py
└── dist/                     built archives (git-ignored)
```

Each archive (`.tar.gz`, `.zip` on Windows) holds `manifest.json` at its root and
the executable at `bin/ai-news-reporter[.exe]`:

| Platform | Archive | Built on |
|---|---|---|
| macOS Apple Silicon | `ai-news-reporter-<version>-darwin-arm64.tar.gz` | `macos-14` |
| macOS Intel | `ai-news-reporter-<version>-darwin-x86_64.tar.gz` | `macos-15`, x64 Python (Rosetta 2) |
| Linux x86_64 (Cloud Agent) | `ai-news-reporter-<version>-linux-x86_64.tar.gz` | `ubuntu-22.04` |
| Windows x64 | `ai-news-reporter-<version>-windows-x86_64.zip` | `windows-latest` |

## Test locally

```bash
P="uv run --project executas/ai-news-reporter"
$P python tests/test_config.py      # app.json / manifest.json / executa.json agree
$P python tests/test_plugin.py      # fake Anna host + fake Tavily, no key needed
$P python scripts/build_binary.py   # build this platform's archive, smoke-test the archived binary
anna-app validate --strict
```

## Publish

1. Run the **Build Executa binaries** workflow (Actions tab, or push a `v<version>` tag).
2. Download the four archives:
   `gh run download <run-id> --pattern 'ai-news-reporter-*' --dir executas/ai-news-reporter/dist`
   (then move them out of the per-artifact subfolders into `dist/`).
3. `anna-app apps publish` — publishes the bundled Executa with its four binaries,
   then the App version.
4. Install the new version and run the full flow on a **Cloud Agent** (Linux)
   before submitting for review.
