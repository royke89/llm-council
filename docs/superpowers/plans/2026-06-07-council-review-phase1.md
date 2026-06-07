# Council Review (Phase 1 — CLI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a project-agnostic `council-review` command that gathers files from any local project, previews cost, runs the existing LLM Council, and saves a markdown report.

**Architecture:** One new module `backend/review.py` with pure, testable helpers (file collection, prompt building, token estimate, report writer) plus a thin `main()` CLI that wires them to the existing `council.run_full_council`. A `council-review.bat` launcher runs the llm-council environment while passing the caller's working directory so it works from any project.

**Tech Stack:** Python 3.10, argparse, asyncio, pytest (dev), uv. Reuses `backend/council.py` and `backend/config.py` unchanged.

---

## File Structure

- Create: `backend/review.py` — file gathering + CLI + report writer
- Create: `tests/test_review.py` — unit tests for the pure helpers
- Create: `council-review.bat` — launcher (repo root)
- Modify: `pyproject.toml` — add `pytest` to a dev dependency group

## Reused interfaces (already exist, do not change)

- `council.run_full_council(user_query: str) -> (stage1, stage2, stage3, metadata)`
  - `stage1`: `list[{"model": str, "response": str}]`
  - `stage2`: `list[{"model": str, "ranking": str, "parsed_ranking": list}]`
  - `stage3`: `{"model": str, "response": str}`
- `config.OPENROUTER_API_KEY`, `config.COUNCIL_MODELS`

---

### Task 1: Add pytest dev dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add pytest dev group**

Run:
```
uv add --dev pytest
```
Expected: `pyproject.toml` gains a `[dependency-groups]` (or `[tool.uv]` dev) entry with `pytest`, and `uv.lock` updates.

- [ ] **Step 2: Verify pytest runs**

Run: `uv run pytest --version`
Expected: prints a pytest version, exit 0.

- [ ] **Step 3: Commit**

```
git add pyproject.toml uv.lock
git commit -m "chore: add pytest dev dependency"
```

---

### Task 2: File collection

**Files:**
- Create: `backend/review.py`
- Test: `tests/test_review.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review.py
from pathlib import Path
from backend.review import collect_files


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_review.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.review'`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/review.py
"""Council Review: gather project files and run the LLM Council on them."""
from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_INCLUDE_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".rb",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".cs", ".php", ".swift", ".kt",
    ".scala", ".sh", ".bash", ".sql", ".html", ".css", ".scss", ".vue",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".md", ".txt",
}
DEFAULT_EXCLUDE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__",
    ".next", ".cache", ".idea", ".vscode", "coverage", ".pytest_cache",
    "council-reviews",
}
DEFAULT_EXCLUDE_GLOBS = [
    "*.min.*", "package-lock.json", "uv.lock", "yarn.lock", "poetry.lock",
    "pnpm-lock.yaml",
]
BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".pdf", ".zip", ".gz",
    ".tar", ".exe", ".dll", ".so", ".dylib", ".class", ".jar", ".woff",
    ".woff2", ".ttf", ".eot", ".mp3", ".mp4", ".mov", ".avi", ".pyc",
}


@dataclass
class CollectionResult:
    included: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    total_bytes: int = 0


def _looks_binary(path: Path) -> bool:
    if path.suffix.lower() in BINARY_EXTS:
        return True
    try:
        chunk = path.read_bytes()[:1024]
    except OSError:
        return True
    return b"\x00" in chunk


def _matches_any(relpath: str, globs) -> bool:
    name = os.path.basename(relpath)
    return any(
        fnmatch.fnmatch(relpath, g) or fnmatch.fnmatch(name, g) for g in globs
    )


def collect_files(root, include_globs=None, exclude_globs=None,
                  max_bytes=200_000, max_file_bytes=100_000) -> CollectionResult:
    root = Path(root)
    exclude_globs = list(DEFAULT_EXCLUDE_GLOBS) + list(exclude_globs or [])
    result = CollectionResult()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in DEFAULT_EXCLUDE_DIRS]
        for fn in filenames:
            abspath = Path(dirpath) / fn
            rel = str(abspath.relative_to(root)).replace("\\", "/")
            if _matches_any(rel, exclude_globs):
                result.skipped.append((rel, "excluded"))
                continue
            if include_globs:
                if not _matches_any(rel, include_globs):
                    continue
            elif abspath.suffix.lower() not in DEFAULT_INCLUDE_EXTS:
                continue
            if _looks_binary(abspath):
                result.skipped.append((rel, "binary"))
                continue
            try:
                size = abspath.stat().st_size
            except OSError:
                result.skipped.append((rel, "unreadable"))
                continue
            if size > max_file_bytes:
                result.skipped.append((rel, "too large"))
                continue
            if result.total_bytes + size > max_bytes:
                result.skipped.append((rel, "over total budget"))
                continue
            try:
                content = abspath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                result.skipped.append((rel, "unreadable"))
                continue
            result.included.append((rel, content))
            result.total_bytes += size
    result.included.sort()
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_review.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```
git add backend/review.py tests/test_review.py
git commit -m "feat: file collection for council-review"
```

---

### Task 3: Prompt builder and token estimate

**Files:**
- Modify: `backend/review.py`
- Test: `tests/test_review.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_review.py
from backend.review import build_review_prompt, estimate_tokens, CollectionResult


def test_build_prompt_contains_question_and_files():
    collected = CollectionResult(included=[("a/b.py", "print(1)")], total_bytes=8)
    prompt = build_review_prompt("find bugs", collected)
    assert "find bugs" in prompt
    assert "a/b.py" in prompt
    assert "print(1)" in prompt


def test_estimate_tokens_roughly_chars_over_four():
    assert estimate_tokens("x" * 400) == 100
    assert estimate_tokens("") >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_review.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_review_prompt'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to backend/review.py
DEFAULT_QUESTION = (
    "Analyze this codebase and give prioritized, concrete suggestions "
    "covering bugs, design, security, and maintainability."
)


def build_review_prompt(question: str, collected: CollectionResult) -> str:
    lines = [
        "You are a panel of expert software reviewers.",
        "Review the project files below and answer the request.",
        "",
        f"REQUEST: {question}",
        "",
        "FILE TREE:",
    ]
    for rel, _ in collected.included:
        lines.append(f"  {rel}")
    lines += ["", "FILE CONTENTS:"]
    for rel, content in collected.included:
        lines += [f"\n----- FILE: {rel} -----", "```", content, "```"]
    return "\n".join(lines)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_review.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```
git add backend/review.py tests/test_review.py
git commit -m "feat: prompt builder and token estimate"
```

---

### Task 4: Report writer

**Files:**
- Modify: `backend/review.py`
- Test: `tests/test_review.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_review.py
from backend.review import write_report


def test_write_report_creates_markdown(tmp_path):
    stage1 = [{"model": "m1", "response": "r1"}]
    stage2 = [{"model": "m1", "ranking": "FINAL RANKING:\n1. Response A"}]
    stage3 = {"model": "chair", "response": "final answer"}
    path = write_report(tmp_path / "out", "do review",
                        [("a.py", "code")], stage1, stage2, stage3, "20260607-120000")
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "final answer" in text
    assert "a.py" in text
    assert "do review" in text
    assert "m1" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_review.py -q`
Expected: FAIL — `ImportError: cannot import name 'write_report'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to backend/review.py
def write_report(out_dir, question, included, stage1, stage2, stage3,
                 timestamp) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"REVIEW-{timestamp}.md"
    lines = [
        f"# Council Review — {timestamp}",
        "",
        f"**Request:** {question}",
        "",
        "## Files reviewed",
        "",
    ]
    for rel, _ in included:
        lines.append(f"- {rel}")
    lines += ["", "## Final synthesis (Chairman)", "",
              str(stage3.get("response", "")), "",
              "## Individual model responses", ""]
    for r in stage1:
        lines += [f"### {r.get('model')}", "", str(r.get("response", "")), ""]
    lines += ["## Peer rankings", ""]
    for r in stage2:
        lines += [f"### {r.get('model')}", "", str(r.get("ranking", "")), ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_review.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```
git add backend/review.py tests/test_review.py
git commit -m "feat: markdown report writer"
```

---

### Task 5: Argument parsing and target resolution

**Files:**
- Modify: `backend/review.py`
- Test: `tests/test_review.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_review.py
from backend.review import parse_args, resolve_target, DEFAULT_QUESTION


def test_parse_args_defaults():
    args = parse_args([])
    assert args.path == "."
    assert args.ask == DEFAULT_QUESTION
    assert args.max_bytes == 200_000
    assert args.yes is False


def test_resolve_target_relative_to_base(tmp_path):
    sub = tmp_path / "proj"
    sub.mkdir()
    resolved = resolve_target("proj", str(tmp_path))
    assert Path(resolved) == sub.resolve()


def test_resolve_target_default_is_base(tmp_path):
    resolved = resolve_target(".", str(tmp_path))
    assert Path(resolved) == tmp_path.resolve()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_review.py -q`
Expected: FAIL — `ImportError: cannot import name 'parse_args'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to backend/review.py
import argparse


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="council-review",
        description="Run the LLM Council on a project's files.",
    )
    p.add_argument("path", nargs="?", default=".",
                   help="Folder to review (default: current directory).")
    p.add_argument("--ask", "-a", default=DEFAULT_QUESTION,
                   help="Question for the council.")
    p.add_argument("--include", action="append", default=[],
                   help="Glob(s) to restrict included files.")
    p.add_argument("--exclude", action="append", default=[],
                   help="Extra glob(s) to skip.")
    p.add_argument("--max-bytes", type=int, default=200_000,
                   help="Total text budget across all files.")
    p.add_argument("--max-file-bytes", type=int, default=100_000,
                   help="Per-file skip threshold.")
    p.add_argument("--out", default=None,
                   help="Report output dir (default: <path>/council-reviews).")
    p.add_argument("--yes", "-y", action="store_true",
                   help="Skip the confirmation prompt.")
    p.add_argument("--base-dir", default=None,
                   help="Directory to resolve relative paths against "
                        "(set by the launcher to the caller's CWD).")
    return p.parse_args(argv)


def resolve_target(path: str, base_dir):
    base = Path(base_dir) if base_dir else Path.cwd()
    target = Path(path)
    if not target.is_absolute():
        target = base / target
    return str(target.resolve())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_review.py -q`
Expected: PASS (10 passed).

- [ ] **Step 5: Commit**

```
git add backend/review.py tests/test_review.py
git commit -m "feat: CLI argument parsing and target resolution"
```

---

### Task 6: CLI main() wiring

**Files:**
- Modify: `backend/review.py`

- [ ] **Step 1: Implement main()**

```python
# append to backend/review.py
import asyncio
from datetime import datetime


def main(argv=None) -> int:
    args = parse_args(argv)
    target = resolve_target(args.path, args.base_dir)
    if not Path(target).is_dir():
        print(f"Error: not a directory: {target}")
        return 1

    from .config import OPENROUTER_API_KEY, COUNCIL_MODELS
    if not OPENROUTER_API_KEY:
        print("Error: OPENROUTER_API_KEY is empty. Add it to the .env file "
              "in the llm-council folder.")
        return 1

    collected = collect_files(
        target,
        include_globs=args.include or None,
        exclude_globs=args.exclude,
        max_bytes=args.max_bytes,
        max_file_bytes=args.max_file_bytes,
    )
    if not collected.included:
        print(f"No matching files found under {target}.")
        return 1

    from .council import run_full_council

    prompt = build_review_prompt(args.ask, collected)
    tokens = estimate_tokens(prompt)
    print(f"Reviewing: {target}")
    print(f"Question:  {args.ask}")
    print(f"Files included: {len(collected.included)} "
          f"(total {collected.total_bytes / 1024:.1f} KB)")
    for rel, _ in collected.included:
        print(f"  + {rel}")
    if collected.skipped:
        print(f"Skipped {len(collected.skipped)} file(s) "
              f"(binary / too large / excluded / over budget).")
    print(f"Estimated input: ~{tokens} tokens sent to each of "
          f"{len(COUNCIL_MODELS)} council members.")
    # Coarse ballpark: blended ~$10 per 1M input tokens across premium models,
    # counting stage-1 fan-out (stage 2/3 and output add more). Rough on purpose.
    est_cost = tokens * len(COUNCIL_MODELS) / 1_000_000 * 10.0
    print(f"Rough cost estimate: ~${est_cost:.2f}+ "
          f"(varies with models and output length).")
    print("This will make PAID API calls to OpenRouter.")

    if not args.yes:
        try:
            resp = input("Proceed? [y/N] ").strip().lower()
        except EOFError:
            resp = ""
        if resp not in ("y", "yes"):
            print("Aborted.")
            return 0

    print("Running the council... (this can take a minute)")
    stage1, stage2, stage3, _meta = asyncio.run(run_full_council(prompt))

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = args.out or str(Path(target) / "council-reviews")
    report = write_report(out_dir, args.ask, collected.included,
                          stage1, stage2, stage3, timestamp)

    print("\n===== COUNCIL FINAL ANALYSIS =====\n")
    print(stage3.get("response", "(no synthesis returned)"))
    print(f"\nModels that responded: {len(stage1)}")
    print(f"Full report saved to: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Smoke-test argument handling without API**

Run: `uv run python -m backend.review --help`
Expected: prints usage including `council-review`, `--ask`, `--base-dir`; exit 0.

- [ ] **Step 3: Verify "no files" path (no API call)**

Run (from repo root): `uv run python -m backend.review docs/superpowers/plans --include "*.nonexistent"`
Expected: prints `No matching files found ...`, exit 1. No API call.

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest -q`
Expected: PASS (10 passed).

- [ ] **Step 5: Commit**

```
git add backend/review.py
git commit -m "feat: council-review CLI main()"
```

---

### Task 7: Launcher for any project + manual end-to-end test

**Files:**
- Create: `council-review.bat`

- [ ] **Step 1: Create the launcher**

```bat
@echo off
REM council-review launcher - run the LLM Council on the current project.
REM Uses the llm-council environment but reviews the folder you run it from.
uv run --directory "C:\Users\royn8\.claude\llm-council" python -m backend.review --base-dir "%CD%" %*
```

- [ ] **Step 2: Put the launcher on PATH**

Check whether `%USERPROFILE%\.local\bin` is on PATH:
Run (PowerShell): `$env:PATH -split ';' | Select-String -SimpleMatch ".local\bin"`
- If it appears: copy `council-review.bat` there:
  `Copy-Item "C:\Users\royn8\.claude\llm-council\council-review.bat" "$env:USERPROFILE\.local\bin\council-review.bat"`
- If it does NOT appear: append the llm-council folder to the user PATH:
  `[Environment]::SetEnvironmentVariable("PATH", $env:PATH + ";C:\Users\royn8\.claude\llm-council", "User")`
  (new terminals pick it up).

- [ ] **Step 3: Manual end-to-end test on a small folder (real API cost)**

Create a tiny throwaway project and review it:
```
mkdir %TEMP%\cr-test
echo def add(a,b): return a-b > %TEMP%\cr-test\calc.py
council-review %TEMP%\cr-test --ask "Is there a bug?" --yes
```
Expected: preview prints `calc.py`, the council runs, the final analysis is printed (it should notice `add` subtracts), and a report appears at `%TEMP%\cr-test\council-reviews\REVIEW-*.md`.

- [ ] **Step 4: Commit**

```
git add council-review.bat
git commit -m "feat: council-review launcher for any project"
```

---

### Task 8: Update README/CLAUDE notes (light)

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a short "Reviewing your own projects" section**

Add usage:
```
council-review [folder] --ask "your question"
```
Document defaults (current dir, smart file selection, 200 KB cap, preview/confirm, report under `council-reviews/`).

- [ ] **Step 2: Commit**

```
git add README.md
git commit -m "docs: document council-review usage"
```

---

## Self-Review

- **Spec coverage:** trigger from any project (Task 5/6/7 `--base-dir` + launcher), smart defaults + caps (Task 2), preview + confirm + cost estimate (Task 6), reuse council unchanged (Task 6 imports), report into target project (Task 6 default `--out`), error handling for no-files/no-key (Task 6), testing (Tasks 2–6). All covered.
- **Placeholder scan:** none — every code step contains full code.
- **Type consistency:** `CollectionResult.included` is `list[(rel, content)]` everywhere; `collect_files`/`build_review_prompt`/`write_report`/`main` agree; stage dict keys (`model`, `response`, `ranking`) match `council.py`.

## Notes / decisions

- Output reports are written into each target project's `council-reviews/` folder; that folder name is in `DEFAULT_EXCLUDE_DIRS` so past reviews are never fed back into new reviews.
- Cost estimate is a coarse token-based dollar ballpark (blended ~$10/1M input tokens) plus a clear "PAID API calls" warning. A precise per-model pricing lookup via the OpenRouter API is intentionally deferred — YAGNI for phase 1; the confirm step already gives the user control.
