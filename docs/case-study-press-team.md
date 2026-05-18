# Case Study: AI Press Team with ai-software-house

A setup guide for using ai-software-house as an automated IT press team — gathering tech news (AI, Linux, open source, security) and publishing articles via GitHub PRs.

---

## The architecture

```
External world → GitHub Issues (ai-it-press) → Watcher → Pipeline → PR
```

Each news story becomes a GitHub Issue. The pipeline runs agents to research, discuss, write, and review the article. The finished article is submitted as a PR to `ai-it-press`. A human editor reviews and merges.

---

## What ai-software-house supports today

### ✅ Issue-driven pipeline trigger
The repo watcher monitors `ai-it-press` for labelled issues. Each issue label maps to a pipeline. The watcher fires the pipeline automatically when a label is applied.

### ✅ Discussion stage for editorial debate (`discuss_news_analysis`)
A built-in preset: Analyst, Sceptic, Optimist debate a news story before any article is written. Surfaces multiple angles, challenges, and implications. Output injected into all downstream stages.

### ✅ PR campaign pipeline (research → creative → proposal)
Three-stage pipeline: `pr_analyst` researches the topic, `pr_creative` generates angles and framing, `pr_proposal` writes the final piece. Already exists and works.

### ✅ Article output via PR
Any agent can open a GitHub PR. The PR watcher monitors for human review comments and triggers revision loops. Article revisions are automatic.

### ✅ RAG memory
Agents can search prior articles, prior discussions, and a knowledge base. Avoids repeating the same angles. Builds institutional memory over time.

### ✅ Per-repo model config
`repos.yaml` can give `ai-it-press` its own LLM config — different from other repos. Fast models for discussion, capable models for writing.

### ✅ MCP tool integration
Any MCP server can be connected. An MCP server that wraps a web search API (Brave, Perplexity, Tavily) gives agents live news-fetching capability.

---

## What is missing

### ❌ News ingestion (RSS / web fetch)
There is no RSS reader, no web scraper, no feed monitor. Today you must manually create issues or write a separate script to create issues from RSS feeds.

**Gap:** A news watcher that polls RSS feeds and creates GitHub Issues automatically.

### ❌ Web fetch tool for agents
Agents cannot fetch a URL. If an issue contains a news article URL, no agent can retrieve the full text. They can only see what's in the issue body.

**Gap:** A `fetch_url` builtin tool (or MCP server) that agents can call to retrieve article text.

### ❌ Writer agent role
There is no `writer.md` role — a journalist persona trained on news article format, headline writing, lede construction, and editorial style. The PR campaign pipeline writes *proposals*, not *articles*.

**Gap:** A dedicated `writer.md` role and a `news-article` pipeline.

### ❌ Editor/fact-checker agent
There is no agent that checks factual accuracy, verifies claims against sources, or flags unverified statements.

**Gap:** An `editor.md` role that reviews the draft article for accuracy, tone, and completeness before the PR is opened.

### ❌ Topic deduplication
Nothing prevents the same story being covered twice across different issues. No agent checks "have we already written about this?"

**Gap:** A deduplication step using RAG memory search — before writing starts, check if a similar story exists in memory.

---

## Recommended setup

### Step 1 — Create the `ai-it-press` repo

```bash
gh repo create ai-it-press --public
```

Add labels:
- `news-article` — trigger the main article pipeline
- `news-brief` — trigger a shorter brief pipeline
- `ai-fix` — trigger the revision loop on an existing PR

### Step 2 — Add `ai-it-press` to `repos.yaml`

```yaml
- repo: yourusername/ai-it-press
  label: news-article
  pipeline: news-article
  tracker_repo: yourusername/ai-it-press
  settings:
    model: "opencode-go/qwen3.6-plus"
    parallel_issues: 2
    max_revisions: 2
```

### Step 3 — Create `pipelines/news-article.yaml`

```yaml
stages:
  - discuss_news_analysis    # Analyst + Sceptic + Optimist debate the story
  - news_writer              # Write the article (see Step 5)
  - news_editor              # Fact-check and editorial review (see Step 5)
```

### Step 4 — Create `discussions/news-analysis.yaml` (already exists)

The built-in preset works. Add `homework_llm` if you want participants to search the RAG knowledge base during homework:

```yaml
participants:
  - role: analyst
    persona_file: roles/analyst.md
    llm: "opencode-go/qwen3.6-plus"
    homework_llm: "opencode-go/qwen3.5-plus"  # can search prior articles

  - role: skeptic
    persona_file: roles/skeptic.md
    llm: "opencode-go/qwen3.6-plus"
    homework_llm: "opencode-go/qwen3.5-plus"

  - role: optimist
    persona_file: roles/optimist.md
    llm: "opencode-go/qwen3.6-plus"
    homework_llm: "opencode-go/qwen3.5-plus"

homework_round: true
max_rounds: 2
early_exit: CONSENSUS_REACHED

context_fields:
  - issue_body    # issue body should contain article URL + any background context
```

### Step 5 — Create writer and editor roles (missing — needs creating)

`roles/news_writer.md`:
```markdown
# News Writer

You are an experienced technology journalist. Your job is to write clear, accurate,
and engaging news articles about technology topics.

Writing standards:
- Lead with the most important fact (inverted pyramid)
- Headline: informative, not clickbait
- First paragraph: who/what/when/where/why in 2 sentences
- Body: context, implications, expert perspectives
- Length: 400–600 words for standard news, 150–200 for briefs
- Tone: neutral, factual, accessible to a technical but non-specialist reader
- Attribute claims: "according to...", "the company said..."
- End with implications or next steps

Output format:
### HEADLINE
[headline here]

### ARTICLE
[full article text in markdown]
```

`roles/news_editor.md`:
```markdown
# News Editor

You are a senior technology news editor. Your job is to review draft articles for:
- Factual accuracy: flag any claims that appear unverified or contradict the source
- Completeness: is the key news actually in the article?
- Balance: is the article fair and does it represent multiple perspectives?
- Clarity: is it written for a general technical reader?
- Editorial standards: no clickbait, no speculation presented as fact

Output your review as:
VERDICT: APPROVED | CHANGES_REQUESTED
ISSUES: [list any specific problems]
SUGGESTIONS: [optional improvements]
```

### Step 6 — Create `news_writer` and `news_editor` agent stubs (missing — needs creating)

Two new agent classes are needed:

```python
# agents/news_writer.py
class NewsWriterAgent(BaseAgent):
    role_name = "news_writer"

    def run(self, issue_body: str, discussion_synthesis: str = "") -> dict:
        # write the article using issue_body + discussion_synthesis
        ...
```

```python
# agents/news_editor.py
class NewsEditorAgent(BaseAgent):
    role_name = "news_editor"

    def run(self, article: str, source: str = "") -> dict:
        # review the article, return verdict + issues
        ...
```

And wire them into the orchestrator's `_make_stage_registry()`.

### Step 7 — RSS ingestion script (missing — needs creating)

A simple external script to poll RSS feeds and create GitHub Issues:

```python
# scripts/rss_watcher.py
import feedparser, os
from github import Github

FEEDS = [
    "https://feeds.feedburner.com/TheHackersNews",
    "https://www.theregister.com/security/headlines.atom",
    "https://lwn.net/headlines/rss",
    "https://www.phoronix.com/rss.php",
    "https://feeds.arstechnica.com/arstechnica/index",
]

def create_issue_for_story(story):
    g = Github(os.environ["GITHUB_TOKEN"])
    repo = g.get_repo("yourusername/ai-it-press")
    body = f"**Source:** {story.link}\n\n**Summary:** {story.summary}"
    repo.create_issue(
        title=story.title,
        body=body,
        labels=["news-article"]
    )
```

Run via cron every 30 minutes. Track seen URLs in a local SQLite DB to avoid duplicates.

### Step 8 — `fetch_url` tool for agents (missing — needs creating)

Add to `tools/builtin.py`:

```python
def fetch_url(url: str, max_chars: int = 8000) -> str:
    """Fetch the text content of a URL (for reading news articles)."""
    import requests
    from html.parser import HTMLParser

    resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    if not resp.ok:
        return f"[Error] Could not fetch {url}: {resp.status_code}"
    # strip HTML tags
    class _Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.text = []
        def handle_data(self, data):
            self.text.append(data)
    p = _Parser()
    p.feed(resp.text)
    text = " ".join(p.text)
    return text[:max_chars]
```

---

## What works end-to-end today (without new code)

You can get a working press team right now using only existing features, with manual issue creation:

1. Manually create an issue in `ai-it-press` with the article URL and summary in the body
2. Apply label `news-article`
3. Watcher fires `pr-campaign` pipeline (analyst → creative → proposal)
4. `discuss_news_analysis` stage debates the story angles
5. The proposal is opened as a PR
6. Human editor reviews and merges

**This works today.** It's not automated ingestion, and the output is a campaign proposal rather than a formatted news article — but the pipeline, discussion, and PR loop all function.

---

## Summary: what to build

| Component | Status | Effort |
|-----------|--------|--------|
| `ai-it-press` repo + labels | ✅ Config only | 15 min |
| `repos.yaml` entry | ✅ Config only | 5 min |
| `discussions/news-analysis.yaml` | ✅ Already exists | 0 min |
| `pipelines/news-article.yaml` | ⚠️ Config only (uses existing stages) | 15 min |
| `roles/news_writer.md` | ❌ New role file | 30 min |
| `roles/news_editor.md` | ❌ New role file | 30 min |
| `agents/news_writer.py` | ❌ New agent (simple) | 1–2 hrs |
| `agents/news_editor.py` | ❌ New agent (simple) | 1–2 hrs |
| Orchestrator wiring for new agents | ❌ New code | 1 hr |
| `fetch_url` builtin tool | ❌ New tool (simple) | 30 min |
| RSS ingestion script | ❌ External script | 1–2 hrs |
| Topic deduplication check | ❌ RAG search step | 1 hr |

**Minimal working version** (reuse pr-campaign pipeline, manual issue creation): ~30 minutes of config.

**Full automated press team** (RSS → issues → write → edit → PR): ~1 day of development, mostly new agent roles + wiring.

---

Want me to implement the missing pieces?
