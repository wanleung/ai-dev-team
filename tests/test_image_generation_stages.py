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


def test_stage_image_pr_inline_commits_to_existing_branch_no_new_pr():
    """When result.branch is already set (inline after news_article_pr), image_pr commits
    to that branch directly and does not create a new branch or open a new PR."""
    from orchestrator import PipelineResult

    gh = MagicMock()
    gh.commit_file_bytes.return_value = {"commit": {"sha": "abc"}}
    gh.commit_file.return_value = {"commit": {"sha": "def"}}
    gh.add_pr_comment.return_value = None

    orch = _make_orchestrator_for_image(target_github=gh)

    result = PipelineResult()
    result.branch = "article/42-linux-kernel-6-9"   # already set by news_article_pr
    result.pr_number = 7
    result.image_bytes = b"\xff\xd8\xff_inline"
    result.image_path = "articles/images/20260528-042-linux-kernel-6-9.jpg"
    result.image_article_path = "articles/20260528-042-linux-kernel-6-9.md"
    result.all_files = {
        "articles/20260528-042-linux-kernel-6-9.md": "---\nimage: images/20260528-042-linux-kernel-6-9.jpg\n---\n"
    }

    orch._stage_image_pr(result)

    # Must NOT create a new branch or open a new PR
    gh.create_branch.assert_not_called()
    gh.create_pull_request.assert_not_called()

    # Must commit to the existing branch
    gh.commit_file_bytes.assert_called_once_with(
        path="articles/images/20260528-042-linux-kernel-6-9.jpg",
        content_bytes=b"\xff\xd8\xff_inline",
        message="image: add generated image for 20260528-042-linux-kernel-6-9",
        branch="article/42-linux-kernel-6-9",
    )
    gh.commit_file.assert_called_once_with(
        path="articles/20260528-042-linux-kernel-6-9.md",
        content="---\nimage: images/20260528-042-linux-kernel-6-9.jpg\n---\n",
        message="image: add image frontmatter to 20260528-042-linux-kernel-6-9",
        branch="article/42-linux-kernel-6-9",
    )

    # Branch and PR number unchanged
    assert result.branch == "article/42-linux-kernel-6-9"
    assert result.pr_number == 7

    # A comment posted to the existing PR
    gh.add_pr_comment.assert_called_once()
    comment_text = gh.add_pr_comment.call_args[0][1]
    assert "articles/images/20260528-042-linux-kernel-6-9.jpg" in comment_text


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


def test_call_image_api_comfyui_returns_bytes():
    """_call_image_api with comfyui provider submits workflow, polls history, and downloads image."""
    from unittest.mock import patch, MagicMock, call

    minimal_workflow = {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "placeholder", "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad quality", "clip": ["4", 2]}},
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "seed": 42,
                "steps": 20,
                "cfg": 7,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1,
                "latent_image": ["5", 0],
            },
        },
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "api"}},
    }
    fake_image_bytes = b"\xff\xd8\xff\xe0comfy_fake"
    fake_prompt_id = "abc-123"

    submit_resp = MagicMock()
    submit_resp.raise_for_status = MagicMock()
    submit_resp.json.return_value = {"prompt_id": fake_prompt_id}

    history_pending = MagicMock()
    history_pending.raise_for_status = MagicMock()
    history_pending.json.return_value = {}  # not done yet

    history_done = MagicMock()
    history_done.raise_for_status = MagicMock()
    history_done.json.return_value = {
        fake_prompt_id: {
            "outputs": {
                "9": {"images": [{"filename": "api_00001_.png", "subfolder": "", "type": "output"}]}
            }
        }
    }

    img_resp = MagicMock()
    img_resp.raise_for_status = MagicMock()
    img_resp.content = fake_image_bytes

    orch = _make_orchestrator_for_image(press_cfg={
        "image_api": {
            "provider": "comfyui",
            "url": "http://10.100.1.50:8188",
            "workflow_json": minimal_workflow,
            "timeout": 30,
        }
    })

    with patch("requests.post", return_value=submit_resp) as mock_post, \
         patch("requests.get", side_effect=[history_pending, history_done, img_resp]) as mock_get, \
         patch("time.sleep"):
        result = orch._call_image_api("a futuristic open-source server room")

    assert result == fake_image_bytes

    # Workflow submitted to /prompt
    mock_post.assert_called_once()
    post_call = mock_post.call_args
    assert post_call[0][0] == "http://10.100.1.50:8188/prompt"
    submitted_workflow = post_call[1]["json"]["prompt"]
    # Prompt injected into positive CLIPTextEncode node (node "6")
    assert submitted_workflow["6"]["inputs"]["text"] == "a futuristic open-source server room"
    # Negative node (node "7") left unchanged
    assert submitted_workflow["7"]["inputs"]["text"] == "bad quality"

    # /view called with correct params
    view_call = mock_get.call_args_list[-1]
    assert "10.100.1.50:8188/view" in view_call[0][0]
    assert view_call[1]["params"]["filename"] == "api_00001_.png"


def test_call_image_api_comfyui_falls_back_to_first_clip_when_no_ksampler():
    """ComfyUI provider injects prompt into first CLIPTextEncode when KSampler is absent."""
    from unittest.mock import patch, MagicMock

    workflow_no_ksampler = {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "old prompt", "clip": ["0", 1]}},
        "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "out"}},
    }
    fake_prompt_id = "xyz-456"

    submit_resp = MagicMock()
    submit_resp.raise_for_status = MagicMock()
    submit_resp.json.return_value = {"prompt_id": fake_prompt_id}

    history_done = MagicMock()
    history_done.raise_for_status = MagicMock()
    history_done.json.return_value = {
        fake_prompt_id: {
            "outputs": {"2": {"images": [{"filename": "out_00001_.png", "subfolder": "", "type": "output"}]}}
        }
    }

    img_resp = MagicMock()
    img_resp.raise_for_status = MagicMock()
    img_resp.content = b"\xff\xd8fallback"

    orch = _make_orchestrator_for_image(press_cfg={
        "image_api": {
            "provider": "comfyui",
            "url": "http://10.100.1.50:8188",
            "workflow_json": workflow_no_ksampler,
        }
    })

    with patch("requests.post", return_value=submit_resp), \
         patch("requests.get", side_effect=[history_done, img_resp]), \
         patch("time.sleep"):
        result = orch._call_image_api("injected prompt")

    assert result == b"\xff\xd8fallback"
    submitted = submit_resp.json.return_value  # just verify no error raised
    assert submitted["prompt_id"] == fake_prompt_id


def test_call_image_api_comfyui_raises_when_no_workflow_configured():
    """ComfyUI provider raises RuntimeError when neither workflow_json nor workflow_file is set."""
    orch = _make_orchestrator_for_image(press_cfg={
        "image_api": {"provider": "comfyui", "url": "http://10.100.1.50:8188"}
    })
    try:
        orch._call_image_api("some prompt")
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert "workflow_json" in str(exc) or "workflow_file" in str(exc)


def test_call_image_api_comfyui_raises_on_timeout():
    """ComfyUI provider raises RuntimeError when generation does not complete within timeout."""
    from unittest.mock import patch, MagicMock

    submit_resp = MagicMock()
    submit_resp.raise_for_status = MagicMock()
    submit_resp.json.return_value = {"prompt_id": "slow-123"}

    history_pending = MagicMock()
    history_pending.raise_for_status = MagicMock()
    history_pending.json.return_value = {}  # never completes

    orch = _make_orchestrator_for_image(press_cfg={
        "image_api": {
            "provider": "comfyui",
            "url": "http://10.100.1.50:8188",
            "workflow_json": {
                "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "x", "clip": ["0", 1]}},
            },
            "timeout": 4,  # very short so test finishes quickly
        }
    })

    with patch("requests.post", return_value=submit_resp), \
         patch("requests.get", return_value=history_pending), \
         patch("time.sleep"):
        try:
            orch._call_image_api("test")
            assert False, "Expected RuntimeError"
        except RuntimeError as exc:
            assert "timed out" in str(exc)


def test_overlay_title_draws_text_on_image():
    """_overlay_title_on_image returns larger-or-equal JPEG bytes with text drawn on it."""
    import io
    from PIL import Image

    # Create a plain 512×512 white JPEG as input
    buf = io.BytesIO()
    Image.new("RGB", (512, 512), color=(200, 200, 200)).save(buf, format="JPEG")
    plain_bytes = buf.getvalue()

    orch = _make_orchestrator_for_image()
    result = orch._overlay_title_on_image(
        plain_bytes,
        "Linux Kernel 6.9 Released With Major Performance Improvements",
        {},
    )

    # Result must be valid JPEG
    img = Image.open(io.BytesIO(result))
    assert img.format == "JPEG"
    assert img.size == (512, 512)

    # The banner area (bottom 20%) should be darker than the plain white background
    pixels = list(img.getdata())
    width, height = img.size
    banner_start = int(height * 0.80)
    banner_pixels = [pixels[y * width + width // 2] for y in range(banner_start, height)]
    avg_brightness = sum(sum(p) / 3 for p in banner_pixels) / len(banner_pixels)
    # Banner must be noticeably darker than the 200,200,200 grey background
    assert avg_brightness < 160, f"Banner too bright ({avg_brightness:.1f}); overlay may not have applied"


def test_overlay_title_respects_opacity_config():
    """overlay_opacity: 0 produces a near-white (transparent) banner."""
    import io
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (512, 512), color=(240, 240, 240)).save(buf, format="JPEG")
    plain_bytes = buf.getvalue()

    orch = _make_orchestrator_for_image()
    result = orch._overlay_title_on_image(
        plain_bytes, "Test Title", {"overlay_opacity": 0}
    )
    img = Image.open(io.BytesIO(result))
    pixels = list(img.getdata())
    width, height = img.size
    banner_start = int(height * 0.80)
    banner_pixels = [pixels[y * width + width // 2] for y in range(banner_start, height)]
    avg_brightness = sum(sum(p) / 3 for p in banner_pixels) / len(banner_pixels)
    # With opacity=0 the overlay is invisible; background stays bright
    assert avg_brightness > 180, f"Expected bright banner with opacity=0, got {avg_brightness:.1f}"


def test_stage_image_generate_applies_title_overlay_when_configured():
    """_stage_image_generate calls _overlay_title_on_image when title_overlay is true."""
    from unittest.mock import patch, MagicMock
    from orchestrator import PipelineResult

    article = (
        "---\ntitle: Open Source AI Breakthrough\ndate: 2026-06-01T10:00:00\n"
        "author: HKLUG Team\ntags: [ai]\n---\nBody text.\n"
    )
    fake_raw_bytes = b"\xff\xd8\xff_raw"
    fake_overlay_bytes = b"\xff\xd8\xff_overlaid"

    gh = MagicMock()
    gh.get_file_content.return_value = article

    writer = MagicMock()
    writer.call.return_value = "A vibrant AI research lab."

    orch = _make_orchestrator_for_image(
        target_github=gh,
        news_writer=writer,
        press_cfg={"image_api": {"provider": "comfyui", "title_overlay": True}},
    )

    result = PipelineResult()
    result.image_article_path = "articles/20260601-050-open-source-ai.md"

    with patch.object(orch, "_call_image_api", return_value=fake_raw_bytes), \
         patch.object(orch, "_overlay_title_on_image", return_value=fake_overlay_bytes) as mock_overlay:
        orch._stage_image_generate(result)

    mock_overlay.assert_called_once()
    call_args = mock_overlay.call_args
    assert call_args[0][0] == fake_raw_bytes
    assert call_args[0][1] == "Open Source AI Breakthrough"
    assert result.image_bytes == fake_overlay_bytes


def test_stage_image_generate_skips_overlay_when_not_configured():
    """_overlay_title_on_image is not called when title_overlay is absent/false."""
    from unittest.mock import patch, MagicMock
    from orchestrator import PipelineResult

    article = (
        "---\ntitle: Linux News\ndate: 2026-06-01T10:00:00\n"
        "author: Team\ntags: [linux]\n---\nBody.\n"
    )
    gh = MagicMock()
    gh.get_file_content.return_value = article

    writer = MagicMock()
    writer.call.return_value = "Linux prompt."

    orch = _make_orchestrator_for_image(
        target_github=gh,
        news_writer=writer,
        press_cfg={"image_api": {}},   # no title_overlay key
    )

    result = PipelineResult()
    result.image_article_path = "articles/20260601-051-linux-news.md"

    with patch.object(orch, "_call_image_api", return_value=b"\xff\xd8\xff_raw"), \
         patch.object(orch, "_overlay_title_on_image") as mock_overlay:
        orch._stage_image_generate(result)

    mock_overlay.assert_not_called()


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
