# Council Review (Phase 2 — Web UI) Implementation Plan

> REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** Add a "Review Project" flow to the web app: pick a folder + question, preview cost, then run the council live in the existing stage tabs, saved as a normal conversation.

**Architecture:** Reuse Phase-1 `backend/review.py` (file gather, prompt, report, estimate) and the existing streaming council. Add two endpoints to `backend/main.py`. On the frontend, add a button + modal and reuse the existing stage-streaming event handling.

**Tech Stack:** FastAPI SSE, React (Vite), existing Stage1/2/3 components.

---

## File Structure

- Modify: `backend/main.py` — add `import os`, `from . import review as review_mod`, request models, `POST /api/review/preview`, `POST /api/conversations/{id}/review/stream`.
- Test: `tests/test_review_api.py` — preview endpoint via FastAPI TestClient (no API cost).
- Modify: `frontend/src/api.js` — `reviewPreview()`, `reviewStream()`.
- Modify: `frontend/src/components/Sidebar.jsx` — "📁 Review Project" button + `onReviewProject` prop.
- Create: `frontend/src/components/ReviewModal.jsx` (+ `ReviewModal.css`) — folder/question form, Preview, Run.
- Modify: `frontend/src/App.jsx` — modal state, `handleRunReview`, shared stream-event handler.

## Reused interfaces

- `review_mod.collect_files`, `build_review_prompt`, `estimate_tokens`, `write_report`, `resolve_target`, `DEFAULT_QUESTION`.
- `council.stage1_collect_responses / stage2_collect_rankings / stage3_synthesize_final / calculate_aggregate_rankings / generate_conversation_title` (already imported in `main.py`).
- `storage.add_user_message / add_assistant_message / update_conversation_title / get_conversation`.

---

### Task 1: Backend preview endpoint (TDD)

**Files:** Modify `backend/main.py`; Test `tests/test_review_api.py`.

- [ ] Write failing test: POST `/api/review/preview` with `{path: <tmp with one .py>}` returns `file_count == 1`, the file in `files`, and numeric `est_tokens`/`est_cost`.
- [ ] Implement `ReviewPreviewRequest` model + endpoint:
  - resolve target via `review_mod.resolve_target(path, base_dir)`; if not a dir → `{"error": ...}`.
  - `collect_files`, build prompt with `DEFAULT_QUESTION`, `estimate_tokens`, cost = `tokens * len(COUNCIL_MODELS)/1e6*10`.
  - return `{target, file_count, files, total_bytes, skipped_count, est_tokens, est_cost}`.
- [ ] Run `uv run pytest tests/test_review_api.py -q` → PASS.
- [ ] Commit.

### Task 2: Backend review stream endpoint

**Files:** Modify `backend/main.py`.

- [ ] Add `ReviewStreamRequest` model and `POST /api/conversations/{id}/review/stream`:
  - 404 if conversation missing.
  - In the SSE generator: validate dir; `collect_files`; if none → `error` event.
  - Build `full_prompt`; store a readable user summary message (`📁 Project review: <target> — <question> (<n> files, <kb> KB)`).
  - Start title task from `question` if first message.
  - Stream `stage1_start/complete`, `stage2_start/complete` (+metadata), `stage3_start/complete` exactly like `send_message_stream`, but using `full_prompt` as the query.
  - `title_complete` if applicable; `storage.add_assistant_message(...)`.
  - Write report to `<target>/council-reviews/REVIEW-<ts>.md`; emit `complete` with `report_path`.
- [ ] Smoke check: `uv run python -c "import backend.main"` imports cleanly.
- [ ] Commit.

### Task 3: Frontend API client

**Files:** Modify `frontend/src/api.js`.

- [ ] Add `reviewPreview(params)` → POST `/api/review/preview`.
- [ ] Add `reviewStream(conversationId, params, onEvent)` mirroring `sendMessageStream` (same SSE parsing loop).
- [ ] Commit.

### Task 4: Sidebar button + ReviewModal

**Files:** Modify `Sidebar.jsx`; Create `ReviewModal.jsx`, `ReviewModal.css`.

- [ ] Sidebar: add a "📁 Review Project" button under "+ New Conversation" calling `onReviewProject`.
- [ ] ReviewModal: controlled inputs for `path` (text), `question` (textarea), collapsible advanced (`include`, `exclude`, `maxKB`). Buttons: **Preview** (calls `api.reviewPreview`, shows file_count/total KB/est_cost/skipped), **Run review** (calls `props.onRun(params)`), **Cancel**. Show errors inline.
- [ ] Commit.

### Task 5: App wiring + shared stream handler

**Files:** Modify `App.jsx`.

- [ ] Extract the stage event switch into `handleStreamEvent(eventType, event)` reused by chat + review.
- [ ] Add `showReview` state; render `<ReviewModal>` when true.
- [ ] `handleRunReview(params)`: `createConversation`, add to list, set current with optimistic user summary + assistant placeholder, then `api.reviewStream(id, params, handleStreamEvent)`; on `complete` → `loadConversations()` and `loadConversation(id)` to sync stored summary + report note.
- [ ] Commit.

### Task 6: End-to-end verification (Playwright)

- [ ] Start backend + frontend.
- [ ] Open app, click "📁 Review Project", enter a tiny temp folder + question, Preview (assert file list + cost), Run.
- [ ] Assert stages render and a report file is created under the temp folder.
- [ ] Commit any fixes.

### Task 7: Docs

- [ ] README: add a short "In the web app" note under the review section.
- [ ] Commit + push to fork.

## Self-Review

- Spec coverage: button+modal (T4), preview/cost (T1,T4), run-as-conversation with live stages (T2,T5), report saved to project (T2), security note (localhost; documented). Covered.
- Reuse: no new council logic; report/gather reused from Phase 1.
- Risk: SSE stream endpoint is verified manually (paid) in T6; pure logic (preview) is unit-tested in T1.
