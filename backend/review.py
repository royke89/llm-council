"""Council Review: gather project files and run the LLM Council on them."""
from __future__ import annotations

import argparse
import asyncio
import fnmatch
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
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

DEFAULT_QUESTION = (
    "Analyze this codebase and give prioritized, concrete suggestions "
    "covering bugs, design, security, and maintainability."
)

# Selectable models per council seat (friendly key -> OpenRouter model id).
# Used by the --gpt/--gemini/--claude/--grok flags and the web dropdowns.
GPT_CHOICES = {
    "gpt-5.1": "openai/gpt-5.1",
    "gpt-5.2": "openai/gpt-5.2",
    "gpt-5.5": "openai/gpt-5.5",
    "gpt-5.5-pro": "openai/gpt-5.5-pro",
}
GEMINI_CHOICES = {
    "gemini-3.1-pro": "google/gemini-3.1-pro-preview",
    "gemini-3.5-flash": "google/gemini-3.5-flash",
}
CLAUDE_CHOICES = {
    "sonnet": "anthropic/claude-sonnet-4.6",
    "sonnet-4.6": "anthropic/claude-sonnet-4.6",
    "opus": "anthropic/claude-opus-4.8",
    "opus-4.6": "anthropic/claude-opus-4.6",
    "opus-4.7": "anthropic/claude-opus-4.7",
    "opus-4.8": "anthropic/claude-opus-4.8",
}
GROK_CHOICES = {
    "grok-4.3": "x-ai/grok-4.3",
    "grok-4.20": "x-ai/grok-4.20",
}

# Chairman (final synthesizer) options — can be any provider.
CHAIRMAN_CHOICES = {
    "gemini-3.1-pro": "google/gemini-3.1-pro-preview",
    "gpt-5.5": "openai/gpt-5.5",
    "opus-4.8": "anthropic/claude-opus-4.8",
    "grok-4.3": "x-ai/grok-4.3",
}

# Per-seat metadata: friendly choices, env var (CLI path), provider prefix
# (used to swap the right entry in the council list for the web path).
SEATS = {
    "gpt": {"choices": GPT_CHOICES, "env": "COUNCIL_GPT_MODEL", "prefix": "openai/"},
    "gemini": {"choices": GEMINI_CHOICES, "env": "COUNCIL_GEMINI_MODEL", "prefix": "google/"},
    "claude": {"choices": CLAUDE_CHOICES, "env": "COUNCIL_CLAUDE_MODEL", "prefix": "anthropic/"},
    "grok": {"choices": GROK_CHOICES, "env": "COUNCIL_GROK_MODEL", "prefix": "x-ai/"},
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


RESPONSE_FORMAT_GUIDANCE = (
    "RESPONSE FORMAT (important): Write so a non-technical person can follow it. "
    "Structure your answer in three sections:\n"
    "1. **In plain English** — 2-4 short sentences with no jargon: what this "
    "project does (if you can tell), its overall state, and whether it looks "
    "safe/ready to use.\n"
    "2. **What to do next** — a numbered list of the most important actions in "
    "priority order. Each item is one plain sentence (a brief 'why' is fine). "
    "Avoid jargon here.\n"
    "3. **Technical details** — the deeper analysis for those who want it; "
    "technical terms are fine in this section only.\n"
    "Keep it concise."
)


SIMPLE_RESPONSE_FORMAT_GUIDANCE = (
    "RESPONSE FORMAT (important): The reader is NOT technical. Keep the whole "
    "answer short and free of jargon. Use only two sections:\n"
    "1. **In plain English** — 2-3 short sentences: what this project is, its "
    "overall state, and whether it's safe/ready to use.\n"
    "2. **What to do next** — a short numbered list of the most important "
    "actions in priority order, each one plain sentence.\n"
    "Do NOT add a technical-details section. Avoid jargon entirely. Be brief."
)


def build_review_prompt(question: str, collected: CollectionResult,
                        simple: bool = False) -> str:
    guidance = SIMPLE_RESPONSE_FORMAT_GUIDANCE if simple else RESPONSE_FORMAT_GUIDANCE
    lines = [
        "You are a panel of expert software reviewers.",
        "Review the project files below and answer the request.",
        "",
        f"REQUEST: {question}",
        "",
        guidance,
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
    p.add_argument("--simple", action="store_true",
                   help="Briefer, non-technical answer (no technical section).")
    p.add_argument("--gpt", choices=list(GPT_CHOICES), metavar="MODEL",
                   help="OpenAI seat: " + ", ".join(GPT_CHOICES) + ".")
    p.add_argument("--gemini", choices=list(GEMINI_CHOICES), metavar="MODEL",
                   help="Google seat: " + ", ".join(GEMINI_CHOICES) + ".")
    p.add_argument("--claude", choices=list(CLAUDE_CHOICES), metavar="MODEL",
                   help="Claude seat: sonnet (4.6, value/default), opus (=4.8), "
                        "opus-4.6, opus-4.7, opus-4.8.")
    p.add_argument("--grok", choices=list(GROK_CHOICES), metavar="MODEL",
                   help="xAI seat: " + ", ".join(GROK_CHOICES) + ".")
    p.add_argument("--chairman", choices=list(CHAIRMAN_CHOICES), metavar="MODEL",
                   help="Final synthesizer: " + ", ".join(CHAIRMAN_CHOICES)
                        + " (default: gemini-3.1-pro).")
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


def _force_utf8_stdout() -> None:
    """Avoid UnicodeEncodeError when models return emoji on non-UTF-8 consoles."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv=None) -> int:
    _force_utf8_stdout()
    args = parse_args(argv)
    # Must be set before config is imported below so it picks up the choices.
    for seat, key in {"gpt": args.gpt, "gemini": args.gemini,
                      "claude": args.claude, "grok": args.grok}.items():
        if key:
            os.environ[SEATS[seat]["env"]] = SEATS[seat]["choices"][key]
    if args.chairman:
        os.environ["COUNCIL_CHAIRMAN_MODEL"] = CHAIRMAN_CHOICES[args.chairman]
    target = resolve_target(args.path, args.base_dir)
    if not Path(target).is_dir():
        print(f"Error: not a directory: {target}")
        return 1

    from .config import OPENROUTER_API_KEY, COUNCIL_MODELS, CHAIRMAN_MODEL
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

    prompt = build_review_prompt(args.ask, collected, simple=args.simple)
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
    print(f"Council: {', '.join(COUNCIL_MODELS)}")
    print(f"Chairman: {CHAIRMAN_MODEL}")
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
