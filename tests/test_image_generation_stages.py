"""Tests for image generation pipeline stages."""
from __future__ import annotations
from unittest.mock import ANY, MagicMock


def test_pipeline_result_has_image_fields():
    """PipelineResult should have image_path, image_bytes, image_article_path fields."""
    from orchestrator import PipelineResult

    result = PipelineResult()
    assert result.image_path is None
    assert result.image_bytes is None
    assert result.image_article_path is None


def _make_orchestrator_for_image(*, target_github=None, news_writer=None, press_cfg=None):
    """Build a minimal Orchestrator stub for image generation tests."""
    from orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.target_github = target_github
    orch.news_writer = news_writer or MagicMock()
    orch.image_prompt_writer = MagicMock()
    orch.image_prompt_writer.call.return_value = "A vibrant cityscape representing open-source innovation."
    orch._press_cfg = press_cfg or {}
    return orch


def test_stage_image_generate_skips_when_image_already_present():
    """_stage_image_generate should skip and not call image API when image: field exists."""
    from orchestrator import PipelineResult

    article_with_image = (
        "---\ntitle: Test\ndate: 2026-05-28T10:00:00\nauthor: A\n"
        "tags: [linux]\nimage: images/existing.jpg\n---\nBody.\n"
    )
    gh = MagicMock()
    gh.get_file_content.return_value = article_with_image

    orch = _make_orchestrator_for_image(target_github=gh)
    result = PipelineResult()
    result.requirement = "articles/20260528-042-test.md"

    orch._stage_image_generate(result)

    assert result.image_bytes is None
    assert result.image_path is None
    orch.news_writer.call.assert_not_called()


def test_stage_image_generate_stores_image_bytes_on_result():
    """_stage_image_generate stores image bytes and path on result."""
    from unittest.mock import patch
    from orchestrator import PipelineResult

    article_no_image = (
        "---\ntitle: Linux 6.9 Released\ndate: 2026-05-28T10:00:00\n"
        "author: HKLUG Team\ntags: [linux]\n---\nLinux kernel released.\n"
    )
    fake_image_bytes = b"\xff\xd8\xff\xe0fake_jpeg"

    gh = MagicMock()
    gh.get_file_content.return_value = article_no_image

    writer = MagicMock()
    writer.call.return_value = "A vibrant cityscape with glowing circuits representing open-source innovation."

    orch = _make_orchestrator_for_image(target_github=gh, news_writer=writer)

    result = PipelineResult()
    result.image_article_path = "articles/20260528-042-linux-6-9-released.md"

    with patch.object(orch, "_call_image_api", return_value=fake_image_bytes):
        orch._stage_image_generate(result)

    assert result.image_bytes == fake_image_bytes
    assert result.image_path == "articles/images/20260528-042-linux-6-9-released.jpg"
    assert result.image_article_path == "articles/20260528-042-linux-6-9-released.md"
    assert "image: images/20260528-042-linux-6-9-released.jpg" in (result.all_files or {}).get(
        "articles/20260528-042-linux-6-9-released.md", ""
    )


def test_stage_image_generate_skips_when_no_target_github():
    """_stage_image_generate returns early when target_github is None."""
    from orchestrator import PipelineResult

    orch = _make_orchestrator_for_image(target_github=None)
    result = PipelineResult()
    result.requirement = "articles/20260528-042-test.md"

    orch._stage_image_generate(result)  # should not raise

    assert result.image_bytes is None


def test_call_image_api_openai_returns_bytes():
    """_call_image_api with openai provider downloads image bytes from the returned URL."""
    from unittest.mock import patch, MagicMock

    orch = _make_orchestrator_for_image(press_cfg={
        "image_api": {"provider": "openai", "api_key_env": "OPENAI_API_KEY", "size": "1024x1024"}
    })

    fake_bytes = b"\xff\xd8\xff_fake"
    fake_resp = MagicMock()
    fake_resp.content = fake_bytes
    fake_resp.raise_for_status = MagicMock()

    fake_image_url = "https://oaidalleapiprodscus.blob.core.windows.net/fake.jpg"

    fake_openai_resp = MagicMock()
    fake_openai_resp.data = [MagicMock(url=fake_image_url)]

    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
        with patch("openai.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_client.images.generate.return_value = fake_openai_resp
            with patch("requests.get", return_value=fake_resp) as mock_get:
                result = orch._call_image_api("test prompt")

    assert result == fake_bytes
    mock_get.assert_called_once_with(fake_image_url, timeout=60)


def test_stage_image_pr_creates_branch_commits_and_opens_pr():
    """_stage_image_pr commits image + article update and opens a PR."""
    from orchestrator import PipelineResult

    gh = MagicMock()
    gh.repo = "owner/ai-it-press"
    gh._request.return_value = {"default_branch": "main"}
    gh.create_branch.return_value = None
    gh.commit_file_bytes.return_value = {"commit": {"sha": "abc"}}
    gh.commit_file.return_value = {"commit": {"sha": "def"}}
    gh.create_pull_request.return_value = {"number": 10, "html_url": "https://github.com/pr/10"}

    orch = _make_orchestrator_for_image(target_github=gh)

    result = PipelineResult()
    result.image_bytes = b"\xff\xd8\xff_fake"
    result.image_path = "articles/images/20260528-042-test-slug.jpg"
    result.image_article_path = "articles/20260528-042-test-slug.md"
    result.all_files = {"articles/20260528-042-test-slug.md": "---\nimage: articles/images/20260528-042-test-slug.jpg\n---\n"}

    orch._stage_image_pr(result)

    gh.create_branch.assert_called_once_with("image/20260528-042-test-slug")
    gh.commit_file_bytes.assert_called_once_with(
        path="articles/images/20260528-042-test-slug.jpg",
        content_bytes=b"\xff\xd8\xff_fake",
        message="image: add generated image for 20260528-042-test-slug",
        branch="image/20260528-042-test-slug",
    )
    gh.commit_file.assert_called_once_with(
        path="articles/20260528-042-test-slug.md",
        content="---\nimage: articles/images/20260528-042-test-slug.jpg\n---\n",
        message="image: add image frontmatter to 20260528-042-test-slug",
        branch="image/20260528-042-test-slug",
    )
    gh.create_pull_request.assert_called_once_with(
        title="image: 20260528-042-test-slug — add generated article image",
        body=ANY,
        head="image/20260528-042-test-slug",
        base="main",
    )
    assert result.pr_number == 10
    assert result.pr_url == "https://github.com/pr/10"


def test_stage_image_pr_adds_error_when_no_image_bytes():
    """_stage_image_pr adds an error when image_bytes is not set."""
    from orchestrator import PipelineResult

    orch = _make_orchestrator_for_image(target_github=MagicMock())
    result = PipelineResult()  # no image_bytes

    orch._stage_image_pr(result)

    assert any("missing image data" in e.message for e in result.errors)


def test_stage_image_pr_adds_error_when_no_target_github():
    """_stage_image_pr adds an error when target_github is None."""
    from orchestrator import PipelineResult

    orch = _make_orchestrator_for_image(target_github=None)
    result = PipelineResult()
    result.image_bytes = b"fake"
    result.image_path = "articles/images/x.jpg"
    result.image_article_path = "articles/x.md"

    orch._stage_image_pr(result)

    assert any("no target_github" in e.message for e in result.errors)


def test_stage_image_generate_uses_image_article_path_when_set():
    """_stage_image_generate should use result.image_article_path (set by news_article_pr)
    instead of result.requirement when running inline in the same pipeline."""
    from unittest.mock import patch
    from orchestrator import PipelineResult

    article_no_image = (
        "---\ntitle: Inline Article\ndate: 2026-05-29T10:00:00\n"
        "author: HKLUG Team\ntags: [linux]\n---\nBody text.\n"
    )
    fake_image_bytes = b"\xff\xd8\xff\xe0inline_jpeg"

    gh = MagicMock()
    # target_github.get_file_content should NOT be called when content is in all_files
    gh.get_file_content.return_value = article_no_image

    writer = MagicMock()
    writer.call.return_value = "Inline prompt."

    orch = _make_orchestrator_for_image(target_github=gh, news_writer=writer)

    result = PipelineResult()
    # Simulate news_article_pr having already run: sets image_article_path + all_files
    result.requirement = "articles/20260529-099-wrong.md"  # should be ignored
    result.image_article_path = "articles/20260529-099-inline-article.md"
    result.all_files = {"articles/20260529-099-inline-article.md": article_no_image}

    with patch.object(orch, "_call_image_api", return_value=fake_image_bytes):
        orch._stage_image_generate(result)

    # Should NOT have fetched from remote — content came from all_files
    gh.get_file_content.assert_not_called()
    assert result.image_bytes == fake_image_bytes
    assert result.image_path == "articles/images/20260529-099-inline-article.jpg"
    assert result.image_article_path == "articles/20260529-099-inline-article.md"


def test_stage_image_generate_falls_back_to_issue_number_search_when_standalone():
    """_stage_image_generate searches target repo by issue number when image_article_path is
    not set (standalone image-article pipeline triggered after article already committed).
    Neither result.image_article_path nor result.requirement contains the file path."""
    from unittest.mock import patch
    from orchestrator import PipelineResult

    article_no_image = (
        "---\ntitle: Standalone Article\ndate: 2026-05-29T10:00:00\n"
        "author: HKLUG Team\ntags: [ai]\n---\nBody.\n"
    )
    fake_image_bytes = b"\xff\xd8\xff\xe0standalone_jpeg"

    gh = MagicMock()
    gh.search_files.return_value = ["articles/20260529-100-standalone-article.md"]
    gh.get_file_content.return_value = article_no_image

    writer = MagicMock()
    writer.call.return_value = "Standalone prompt."

    orch = _make_orchestrator_for_image(target_github=gh, news_writer=writer)

    result = PipelineResult()
    result.issue_number = 100
    result.requirement = "**Source:** Ars Technica\n**URL:** https://example.com\nSummary text."
    # image_article_path is NOT set (None) — standalone run

    with patch.object(orch, "_call_image_api", return_value=fake_image_bytes):
        orch._stage_image_generate(result)

    # Should have searched by issue number pattern (default branch, ref=None)
    gh.search_files.assert_called_once_with("articles/*-100-*.md", ref=None)
    # Should have fetched the found article (no ref needed — default branch)
    gh.get_file_content.assert_called_once_with("articles/20260529-100-standalone-article.md", ref=None)
    assert result.image_bytes == fake_image_bytes
    assert result.image_path == "articles/images/20260529-100-standalone-article.jpg"


def test_stage_image_generate_finds_article_on_pr_branch_when_not_merged():
    """_stage_image_generate falls back to open PR branches when article is not on default branch yet."""
    from unittest.mock import patch, call
    from orchestrator import PipelineResult

    article_no_image = (
        "---\ntitle: Unmerged Article\ndate: 2026-05-29T10:00:00\n"
        "author: HKLUG Team\ntags: [ai]\n---\nBody.\n"
    )
    fake_image_bytes = b"\xff\xd8\xff\xe0pr_branch_jpeg"

    gh = MagicMock()
    # Default branch has no match; PR branch has the file
    gh.search_files.side_effect = lambda pattern, ref=None: (
        [] if ref is None else ["articles/20260529-100-unmerged-article.md"]
    )
    gh.list_open_prs.return_value = [{"head": {"ref": "article/100-issue-100"}}]
    gh.get_file_content.return_value = article_no_image

    writer = MagicMock()
    writer.call.return_value = "PR branch prompt."
    orch = _make_orchestrator_for_image(target_github=gh, news_writer=writer)

    result = PipelineResult()
    result.issue_number = 100
    result.requirement = "Issue body text"

    with patch.object(orch, "_call_image_api", return_value=fake_image_bytes):
        orch._stage_image_generate(result)

    gh.list_open_prs.assert_called_once_with(head_pattern="100")
    gh.get_file_content.assert_called_once_with(
        "articles/20260529-100-unmerged-article.md", ref="article/100-issue-100"
    )
    assert result.image_bytes == fake_image_bytes


def test_stage_image_generate_errors_when_no_article_found_for_issue():
    """_stage_image_generate adds an error when no article file matches the issue number."""
    from orchestrator import PipelineResult

    gh = MagicMock()
    gh.search_files.return_value = []
    gh.list_open_prs.return_value = []

    orch = _make_orchestrator_for_image(target_github=gh)

    result = PipelineResult()
    result.issue_number = 999
    result.requirement = "Some issue body text, not a path"

    orch._stage_image_generate(result)

    assert any("no article found" in str(e) for e in result.errors), result.errors


def test_news_article_pr_sets_image_article_path_on_result():
    """_stage_news_article_pr should set result.image_article_path to the committed article path."""
    from orchestrator import PipelineResult, Orchestrator

    article = (
        "---\ntitle: Test Article\ndate: 2026-05-29T10:00:00\n"
        "author: HKLUG Team\ntags: [ai]\nsource_url: https://example.com/story\n---\nBody.\n"
    )

    gh = MagicMock()
    gh.repo = "owner/ai-it-press"
    gh._request.return_value = {"default_branch": "main"}
    gh.create_branch.return_value = None
    gh.commit_file.return_value = {"commit": {"sha": "abc"}}
    gh.create_pull_request.return_value = {"number": 5, "html_url": "https://github.com/pr/5"}

    orch = Orchestrator.__new__(Orchestrator)
    orch.target_github = gh
    orch._press_cfg = {}

    result = PipelineResult()
    result.issue_number = 42
    result.article = article
    result.article_zh_hk = ""
    result.article_zh_tw = ""

    orch._stage_news_article_pr(result)

    # image_article_path must be set to the committed filename
    assert result.image_article_path is not None
    assert result.image_article_path.startswith("articles/")
    assert result.image_article_path.endswith(".md")
    assert "20260529" in result.image_article_path
    assert "42" in result.image_article_path


def test_stage_image_generate_uses_image_prompt_writer_when_available():
    """_stage_image_generate should use image_prompt_writer agent, not news_writer."""
    from unittest.mock import patch
    from orchestrator import PipelineResult

    article_no_image = (
        "---\ntitle: Test Article\ndate: 2026-05-28T10:00:00\n"
        "author: HKLUG Team\ntags: [linux]\n---\nArticle body.\n"
    )
    fake_image_bytes = b"\xff\xd8\xff\xe0fake_jpeg"

    gh = MagicMock()
    gh.get_file_content.return_value = article_no_image

    # news_writer uses mimo-v2.5-pro; should NOT be called
    default_writer = MagicMock()
    default_writer.call.return_value = "should not be used"

    # dedicated image_prompt_writer returns proper prompt
    prompt_writer = MagicMock()
    prompt_writer.call.return_value = "A sleek server rack with glowing indicators."

    orch = _make_orchestrator_for_image(target_github=gh, news_writer=default_writer)
    orch.image_prompt_writer = prompt_writer

    result = PipelineResult()
    result.image_article_path = "articles/20260528-042-linux-6-9-released.md"

    with patch.object(orch, "_call_image_api", return_value=fake_image_bytes):
        orch._stage_image_generate(result)

    # Should use image_prompt_writer, NOT news_writer
    prompt_writer.call.assert_called_once()
    default_writer.call.assert_not_called()
    assert result.image_bytes == fake_image_bytes


def test_build_utility_stages_includes_image_stages():
    """_build_utility_stages registers image_generate and image_pr."""
    orch = _make_orchestrator_for_image(target_github=MagicMock())
    stages = orch._build_utility_stages()

    assert "image_generate" in stages
    assert "image_pr" in stages

    for stage_key in ["image_generate", "image_pr"]:
        stage = stages[stage_key]
        assert stage.name == stage_key
        assert stage.checkpoint_key == stage_key
        assert callable(stage.fn)
        assert stage.label
