# Design: Cantonese Translation Stages for AI Press Team

**Date:** 2026-05-19  
**Status:** Approved  

## Overview

Add two translation pipeline stages to the ai-software-house press team pipeline. After the English article is finalised by `news_editor`, two new stages translate it into:

1. **Written Cantonese** (`zh-hk`) — informal 口語書面語 as used in Hong Kong press (e.g. 蘋果日報 style)
2. **Traditional Chinese** (`zh-tw`) — formal 正式繁體中文 as used in Taiwan/HK broadsheet press

Both translated articles are committed in the same PR as the English article, as separate `.md` files.

## Architecture

### Single `TranslatorAgent`

One agent class, two pipeline stages. The `target_language` parameter determines the output style. This avoids code duplication while keeping stages independently checkpointable and retriable.

```
news_editor (result.article)
    ├── translate_cantonese    → result.article_zh_hk
    └── translate_zh_traditional → result.article_zh_tw
                                        ↓
                               news_article_pr  (commits all 3 files)
```

### New Files

| File | Purpose |
|------|---------|
| `agents/translator.py` | `TranslatorAgent(BaseAgent)` — translates a finalised article |
| `roles/translator.md` | Role instructions covering both language targets |

### PipelineResult New Fields

| Field | Type | Description |
|-------|------|-------------|
| `article_zh_hk` | `str` | Written Cantonese article (full markdown + frontmatter) |
| `article_zh_tw` | `str` | Traditional Chinese article (full markdown + frontmatter) |

### TranslatorAgent Interface

```python
class TranslatorAgent(BaseAgent):
    role_name = "translator"

    def run(self, article: str, target_language: str) -> dict:
        """Translate article.
        
        Args:
            article: Full markdown article with YAML frontmatter (English)
            target_language: "cantonese" | "traditional_chinese"
        
        Returns:
            dict with key:
                - translated_article (str): Full markdown with translated frontmatter
        """
```

### Orchestrator Changes

**New stages registered in `_build_stage_registry()`:**

```python
"translate_cantonese": PipelineStage(
    name="translate_cantonese",
    label="🀄 Translate (Cantonese)",
    description="Translating article to Written Cantonese...",
    checkpoint_key="translate_cantonese",
    fn=lambda r: self._stage_translate(r, "cantonese", "article_zh_hk"),
),
"translate_zh_traditional": PipelineStage(
    name="translate_zh_traditional",
    label="🀄 Translate (Traditional Chinese)",
    description="Translating article to Traditional Chinese...",
    checkpoint_key="translate_zh_traditional",
    fn=lambda r: self._stage_translate(r, "traditional_chinese", "article_zh_tw"),
),
```

**New `_stage_translate()` method:**

```python
def _stage_translate(self, result, target_language: str, result_field: str) -> None:
    source = result.article or result.article_draft
    if not source.strip():
        raise RuntimeError("translate: no article to translate")
    out = self.translator.run(source, target_language=target_language)
    translated = out.get("translated_article", "")
    if not translated.strip():
        raise RuntimeError(f"translate ({target_language}): empty output")
    setattr(result, result_field, translated)
```

**`_stage_news_article_pr()` updated** to include translation files when present:

```python
extra_files = {}
if result.article_zh_hk.strip():
    extra_files[filename.replace(".md", ".zh-hk.md")] = result.article_zh_hk
if result.article_zh_tw.strip():
    extra_files[filename.replace(".md", ".zh-tw.md")] = result.article_zh_tw
result.all_files = {filename: article, **extra_files}
```

### Role Prompt (`roles/translator.md`)

The translator role has:
- Language-specific style guidance for each target
- Instruction to translate ALL frontmatter fields (title, tags) not just body
- Instruction to preserve YAML structure and markdown formatting
- Instruction to keep `source_url` and `author` fields unchanged
- "Cantonese" section: informal tone, 口語詞彙, Hong Kong idioms acceptable
- "Traditional Chinese" section: formal broadsheet register, no colloquialisms

### LLM Config

`translator` agent uses `opencode/opencode-go/qwen3.5-plus` (good multilingual capability) with `ollama/thinker` fallback — same pattern as `news_writer`/`news_editor`.

Add to `config.local.yaml` overrides:
```yaml
translator:
  model: "opencode/opencode-go/qwen3.5-plus"
  opencode_stream: true
  fallbacks:
    - model: "ollama/thinker"
      ollama_think: false
      ollama_stream: true
```

### Pipeline YAML (`ai-it-press/pipelines/news-article.yaml`)

```yaml
stages:
  - discuss_news_analysis
  - news_writer
  - discuss_news_draft
  - news_editor
  - translate_cantonese
  - translate_zh_traditional
  - news_article_pr
```

## Error Handling

- Translation failures are non-fatal: if `translate_cantonese` fails, `translate_zh_traditional` and `news_article_pr` still run (English article is still published)
- Empty translation output raises `RuntimeError` → stage marked failed, pipeline continues to next stage
- Missing `article` field (editor failed upstream) raises `RuntimeError` immediately

## Testing

- Unit test `TranslatorAgent.run()` — mock LLM, verify prompt contains target language instruction and article content
- Unit test `_stage_translate()` — empty article raises, empty output raises, success sets result field
- Unit test `_stage_news_article_pr()` — with zh-hk/zh-tw populated, `result.all_files` contains 3 entries; with only English, contains 1 entry
