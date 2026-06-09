from pathlib import Path

from backend.review import (
    CollectionResult,
    DEFAULT_QUESTION,
    build_review_prompt,
    collect_files,
    estimate_tokens,
    parse_args,
    resolve_target,
    write_report,
)


def _write(p: Path, text: str = "x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_collect_includes_source_and_skips_junk(tmp_path):
    _write(tmp_path / "main.py", "print('hi')")
    _write(tmp_path / "README.md", "# hi")
    _write(tmp_path / ".git" / "config", "[core]")
    _write(tmp_path / "node_modules" / "lib.js", "x")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\x00\x00")
    _write(tmp_path / "package-lock.json", "{}")

    result = collect_files(tmp_path)
    rels = {rel for rel, _ in result.included}
    assert "main.py" in rels
    assert "README.md" in rels
    assert not any(r.startswith(".git") for r in rels)
    assert not any(r.startswith("node_modules") for r in rels)
    assert "logo.png" not in rels
    assert "package-lock.json" not in rels


def test_collect_respects_total_cap(tmp_path):
    _write(tmp_path / "a.py", "a" * 600)
    _write(tmp_path / "b.py", "b" * 600)
    result = collect_files(tmp_path, max_bytes=800)
    assert result.total_bytes <= 800
    assert len(result.included) == 1
    assert any(reason == "over total budget" for _, reason in result.skipped)


def test_collect_per_file_cap(tmp_path):
    _write(tmp_path / "big.py", "x" * 2000)
    result = collect_files(tmp_path, max_file_bytes=1000)
    assert all(rel != "big.py" for rel, _ in result.included)


def test_collect_include_globs_override(tmp_path):
    _write(tmp_path / "keep.py", "1")
    _write(tmp_path / "skip.md", "2")
    result = collect_files(tmp_path, include_globs=["*.py"])
    rels = {rel for rel, _ in result.included}
    assert rels == {"keep.py"}


def test_build_prompt_contains_question_and_files():
    collected = CollectionResult(included=[("a/b.py", "print(1)")], total_bytes=8)
    prompt = build_review_prompt("find bugs", collected)
    assert "find bugs" in prompt
    assert "a/b.py" in prompt
    assert "print(1)" in prompt


def test_build_prompt_includes_plain_language_guidance():
    collected = CollectionResult(included=[("a.py", "x")], total_bytes=1)
    prompt = build_review_prompt("find bugs", collected)
    assert "In plain English" in prompt
    assert "What to do next" in prompt
    assert "Technical details" in prompt


def test_simple_mode_is_briefer_and_drops_technical_section():
    collected = CollectionResult(included=[("a.py", "x")], total_bytes=1)
    prompt = build_review_prompt("find bugs", collected, simple=True)
    assert "In plain English" in prompt
    assert "What to do next" in prompt
    assert "only two sections" in prompt
    assert "3. **Technical details**" not in prompt


def test_estimate_tokens_roughly_chars_over_four():
    assert estimate_tokens("x" * 400) == 100
    assert estimate_tokens("") >= 1


def test_write_report_creates_markdown(tmp_path):
    stage1 = [{"model": "m1", "response": "r1"}]
    stage2 = [{"model": "m1", "ranking": "FINAL RANKING:\n1. Response A"}]
    stage3 = {"model": "chair", "response": "final answer"}
    path = write_report(tmp_path / "out", "do review",
                        [("a.py", "code")], stage1, stage2, stage3,
                        "20260607-120000")
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "final answer" in text
    assert "a.py" in text
    assert "do review" in text
    assert "m1" in text


def test_parse_args_defaults():
    args = parse_args([])
    assert args.path == "."
    assert args.ask == DEFAULT_QUESTION
    assert args.max_bytes == 200_000
    assert args.yes is False
    assert args.simple is False


def test_parse_args_simple_flag():
    assert parse_args(["--simple"]).simple is True


def test_parse_args_claude_choice():
    from backend.review import CLAUDE_CHOICES
    assert parse_args([]).claude is None
    assert parse_args(["--claude", "opus"]).claude == "opus"
    assert parse_args(["--claude", "opus-4.7"]).claude == "opus-4.7"
    assert CLAUDE_CHOICES["opus"] == "anthropic/claude-opus-4.8"
    assert CLAUDE_CHOICES["sonnet"] == "anthropic/claude-sonnet-4.6"
    assert CLAUDE_CHOICES["opus-4.6"] == "anthropic/claude-opus-4.6"
    assert CLAUDE_CHOICES["opus-4.7"] == "anthropic/claude-opus-4.7"
    assert CLAUDE_CHOICES["opus-4.8"] == "anthropic/claude-opus-4.8"


def test_resolve_target_relative_to_base(tmp_path):
    sub = tmp_path / "proj"
    sub.mkdir()
    resolved = resolve_target("proj", str(tmp_path))
    assert Path(resolved) == sub.resolve()


def test_resolve_target_default_is_base(tmp_path):
    resolved = resolve_target(".", str(tmp_path))
    assert Path(resolved) == tmp_path.resolve()
