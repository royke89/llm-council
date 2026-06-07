# Council Review — Design Spec

Date: 2026-06-07
Status: Approved (design), pending implementation plan

## Goal

Let the LLM Council read files from **any** local project and produce an
analysis with concrete, prioritized suggestions. Two phases:

- **Phase 1:** a project-agnostic command (`council-review`) usable from any
  project's terminal in Antigravity IDE.
- **Phase 2:** a web-app option (folder field in the existing browser UI).

This spec covers Phase 1 in full and sketches Phase 2 for a later pass.

## Non-goals

- Editing code (that is Claude Code's job; the council only analyzes/advises).
- Changing the existing council logic (`council.py`, `openrouter.py`, `config.py`
  stay as-is and are reused unchanged).

## Phase 1 — `council-review` command

### Usage

Run from the terminal of *any* project (not just llm-council):

```
council-review [PATH] --ask "review for bugs and design issues"
```

- `PATH` (positional, optional): folder to review. Default: the directory you
  run the command from (the caller's CWD).
- `--ask, -a`: the question for the council. Default:
  "Analyze this codebase and give prioritized, concrete suggestions covering
  bugs, design, security, and maintainability."
- `--include`: glob(s) to restrict which files are sent (e.g. `src/**/*.py`).
- `--exclude`: extra glob(s) to skip, on top of the built-in defaults.
- `--max-bytes`: total text budget across all files. Default 200000 (~200 KB).
- `--max-file-bytes`: per-file skip threshold. Default 100000 (~100 KB).
- `--out`: report output directory. Default `<PATH>/council-reviews/`.
- `--yes, -y`: skip the confirmation prompt.

### Multi-project requirement

The tool must work for many projects, not one:

- `PATH` may be any absolute or relative folder; relative paths resolve against
  the directory the user invoked the command from.
- A launcher (`council-review`) makes it callable from any directory without
  `cd`-ing into the llm-council folder. The launcher preserves the caller's
  working directory so a bare `council-review` reviews the project you're in.
- Reports are written into the **target** project's folder (default
  `<PATH>/council-reviews/`), so each project keeps its own reviews.

### Behavior

1. **Collect files** under `PATH`:
   - Default include: common source/text extensions (e.g. .py, .js, .ts, .tsx,
     .jsx, .java, .go, .rs, .rb, .c, .h, .cpp, .cs, .php, .swift, .kt, .scala,
     .sh, .sql, .html, .css, .scss, .json, .yaml, .yml, .toml, .md, .txt, etc.).
     If `--include` is given, it overrides the default include set.
   - Default exclude (always applied): `.git`, `node_modules`, `.venv`, `venv`,
     `dist`, `build`, `__pycache__`, `.next`, `.cache`, lockfiles
     (package-lock.json, uv.lock, yarn.lock, poetry.lock), minified files
     (*.min.*), and any path matched by `--exclude`.
   - Skip binary files (extension blocklist + null-byte sniff) and any file
     larger than `--max-file-bytes`.
   - Accumulate file text until `--max-bytes` is reached; record which files
     were included vs. skipped (and why).

2. **Preview + confirm (cost guardrail):** print included file list, total
   bytes, estimated input tokens (chars/4), and a best-effort cost estimate
   (using OpenRouter model pricing when available; degrade to tokens-only if
   not). Then prompt `Proceed? [y/N]` unless `--yes`.

3. **Build the council prompt:** a header instructing the council to act as
   code reviewers, the user's question, a file tree summary, then each file's
   contents fenced and labeled with its relative path.

4. **Run the council:** call the existing
   `council.run_full_council(content)` — all 4 council models + chairman,
   unchanged.

5. **Output:**
   - Print the chairman's final synthesis (stage 3) to the terminal.
   - Write a full markdown report to `--out` named `REVIEW-<timestamp>.md`,
     containing: the question, the included-files list, every model's stage-1
     response, the stage-2 rankings, and the stage-3 final synthesis.

### New code

- One new module: `backend/review.py` — argument parsing, file gathering,
  preview/confirm, prompt assembly, council invocation, report writing.
- One launcher: `council-review` wrapper (Windows `.bat`) that invokes the
  llm-council environment while preserving the caller's working directory.
- No changes to `council.py`, `openrouter.py`, or `config.py`.

### Error handling

- No files matched → clear message, exit without calling models.
- Missing/empty `OPENROUTER_API_KEY` → clear message pointing to `.env`.
- A model failing mid-run → handled by existing council graceful degradation;
  the report notes any model that returned nothing.
- Total exceeds `--max-bytes` → include up to the cap, clearly list what was
  skipped so the user can narrow scope or raise the cap.

### Testing

- File collection (no API cost): against a temp directory, assert excludes,
  per-file cap, total cap, and `--include`/`--exclude` behavior.
- Prompt assembly: assert file paths and contents appear in the built prompt.
- One real end-to-end run on a small folder to confirm the report is produced.

## Phase 2 — Web app (later, separate plan)

- Add a "project folder" path + question input to the existing frontend.
- New backend endpoint reuses `review.py`'s file-gathering to build the prompt,
  then runs the council and returns results rendered in the existing stage tabs.
- Same cost-preview concept surfaced in the UI before running.
- Details to be brainstormed/planned when Phase 1 is working.
