"""FastAPI backend for LLM Council."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any
import uuid
import json
import asyncio
import os
from datetime import datetime

from . import storage
from . import review as review_mod
from .config import COUNCIL_MODELS
from .council import run_full_council, generate_conversation_title, stage1_collect_responses, stage2_collect_rankings, stage3_synthesize_final, calculate_aggregate_rankings

app = FastAPI(title="LLM Council API")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    pass


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""
    id: str
    created_at: str
    title: str
    message_count: int


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    created_at: str
    title: str
    messages: List[Dict[str, Any]]


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "LLM Council API"}


@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations():
    """List all conversations (metadata only)."""
    return storage.list_conversations()


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(request: CreateConversationRequest):
    """Create a new conversation."""
    conversation_id = str(uuid.uuid4())
    conversation = storage.create_conversation(conversation_id)
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str):
    """Get a specific conversation with all its messages."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.post("/api/conversations/{conversation_id}/message")
async def send_message(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and run the 3-stage council process.
    Returns the complete response with all stages.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    # Add user message
    storage.add_user_message(conversation_id, request.content)

    # If this is the first message, generate a title
    if is_first_message:
        title = await generate_conversation_title(request.content)
        storage.update_conversation_title(conversation_id, title)

    # Run the 3-stage council process
    stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
        request.content
    )

    # Add assistant message with all stages
    storage.add_assistant_message(
        conversation_id,
        stage1_results,
        stage2_results,
        stage3_result
    )

    # Return the complete response with metadata
    return {
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage3": stage3_result,
        "metadata": metadata
    }


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and stream the 3-stage council process.
    Returns Server-Sent Events as each stage completes.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    async def event_generator():
        try:
            # Add user message
            storage.add_user_message(conversation_id, request.content)

            # Start title generation in parallel (don't await yet)
            title_task = None
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(request.content))

            # Stage 1: Collect responses
            yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"
            stage1_results = await stage1_collect_responses(request.content)
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"

            # Stage 2: Collect rankings
            yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
            stage2_results, label_to_model = await stage2_collect_rankings(request.content, stage1_results)
            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
            yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings}})}\n\n"

            # Stage 3: Synthesize final answer
            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
            stage3_result = await stage3_synthesize_final(request.content, stage1_results, stage2_results)
            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"

            # Wait for title generation if it was started
            if title_task:
                title = await title_task
                storage.update_conversation_title(conversation_id, title)
                yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

            # Save complete assistant message
            storage.add_assistant_message(
                conversation_id,
                stage1_results,
                stage2_results,
                stage3_result
            )

            # Send completion event
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except Exception as e:
            # Send error event
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


class ReviewPreviewRequest(BaseModel):
    """Request to preview which files a project review would send."""
    path: str
    include: List[str] = []
    exclude: List[str] = []
    max_bytes: int = 200000
    max_file_bytes: int = 100000
    base_dir: str | None = None
    simple: bool = False


class ReviewStreamRequest(ReviewPreviewRequest):
    """Request to run a project review (streamed)."""
    question: str = ""


@app.post("/api/review/preview")
async def review_preview(req: ReviewPreviewRequest):
    """Return the files, size, and cost estimate for a prospective review."""
    target = review_mod.resolve_target(req.path, req.base_dir)
    if not os.path.isdir(target):
        return {"error": f"Not a directory: {target}"}
    collected = review_mod.collect_files(
        target,
        include_globs=req.include or None,
        exclude_globs=req.exclude,
        max_bytes=req.max_bytes,
        max_file_bytes=req.max_file_bytes,
    )
    prompt = review_mod.build_review_prompt(review_mod.DEFAULT_QUESTION, collected, simple=req.simple)
    tokens = review_mod.estimate_tokens(prompt)
    est_cost = round(tokens * len(COUNCIL_MODELS) / 1_000_000 * 10.0, 2)
    return {
        "target": target,
        "file_count": len(collected.included),
        "files": [rel for rel, _ in collected.included],
        "total_bytes": collected.total_bytes,
        "skipped_count": len(collected.skipped),
        "est_tokens": tokens,
        "est_cost": est_cost,
    }


@app.post("/api/conversations/{conversation_id}/review/stream")
async def review_stream(conversation_id: str, req: ReviewStreamRequest):
    """Build a prompt from a project's files and stream the council review."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    question = req.question.strip() or review_mod.DEFAULT_QUESTION
    target = review_mod.resolve_target(req.path, req.base_dir)
    is_first_message = len(conversation["messages"]) == 0

    async def event_generator():
        try:
            if not os.path.isdir(target):
                yield f"data: {json.dumps({'type': 'error', 'message': f'Not a directory: {target}'})}\n\n"
                return

            collected = review_mod.collect_files(
                target,
                include_globs=req.include or None,
                exclude_globs=req.exclude,
                max_bytes=req.max_bytes,
                max_file_bytes=req.max_file_bytes,
            )
            if not collected.included:
                yield f"data: {json.dumps({'type': 'error', 'message': f'No matching files under {target}'})}\n\n"
                return

            full_prompt = review_mod.build_review_prompt(question, collected, simple=req.simple)
            kb = collected.total_bytes / 1024
            summary = (
                f"\U0001f4c1 Project review: {target}\n\n"
                f"**Request:** {question}\n\n"
                f"_{len(collected.included)} files, {kb:.1f} KB_"
            )
            storage.add_user_message(conversation_id, summary)

            title_task = None
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(question))

            yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"
            stage1_results = await stage1_collect_responses(full_prompt)
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"

            yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
            stage2_results, label_to_model = await stage2_collect_rankings(full_prompt, stage1_results)
            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
            yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings}})}\n\n"

            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
            stage3_result = await stage3_synthesize_final(full_prompt, stage1_results, stage2_results)
            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"

            if title_task:
                title = await title_task
                storage.update_conversation_title(conversation_id, title)
                yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

            storage.add_assistant_message(
                conversation_id, stage1_results, stage2_results, stage3_result
            )

            report_path = None
            try:
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                report = review_mod.write_report(
                    os.path.join(target, "council-reviews"),
                    question, collected.included,
                    stage1_results, stage2_results, stage3_result, timestamp,
                )
                report_path = str(report)
            except Exception:
                report_path = None

            yield f"data: {json.dumps({'type': 'complete', 'report_path': report_path})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
