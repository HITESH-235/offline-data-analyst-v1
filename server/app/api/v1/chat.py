"""
Chat endpoint — simplified to use the Agent loop.

Flow:
  1. Validate dataset exists
  2. Log user message to DB
  3. Classify intent using QueryPlanner
  4. Run Agent.run() with the classified intent
  5. Save assistant response to DB and return
"""

import asyncio
import json
import time
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from app.storage.sqlite.session import SessionLocal, get_db
from app.models.chat import ChatRequest, DBChatHistory
from app.services.dataset_manager import DatasetManager
from app.services.metadata_service import MetadataService
from app.llm.planner import QueryPlanner
from app.llm.agent import Agent

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post("/message", status_code=status.HTTP_200_OK)
def handle_chat_message(
    request: ChatRequest,
    db: Session = Depends(get_db)
):
    return process_chat_message(request, db, lambda stage: None)[0]


@router.post("/message/stream")
async def stream_chat_message(request: ChatRequest):
    loop = asyncio.get_running_loop()
    events = asyncio.Queue()
    start = time.monotonic()

    def emit(stage, **payload):
        event = {"stage": stage, "elapsed_ms": round((time.monotonic() - start) * 1000), **payload}
        loop.call_soon_threadsafe(events.put_nowait, event)

    def run():
        try:
            with SessionLocal() as db:
                result, failed = process_chat_message(request, db, emit)
            emit("failed" if failed else "completed", result=result)
        except HTTPException as error:
            emit("failed", error=error.detail)
        except Exception:
            emit("failed", error="The analyst could not finish the request.")

    async def stream():
        worker = asyncio.create_task(run_in_threadpool(run))
        while True:
            event = await events.get()
            yield json.dumps(event) + "\n"
            if event["stage"] in {"completed", "failed"}:
                await worker
                return

    return StreamingResponse(stream(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def process_chat_message(request, db, emit):
    dataset_id = request.dataset_id
    project_id = request.project_id
    user_msg = request.message

    # --- Step 1: Validate dataset and profile exist ---
    db_dataset = DatasetManager.get_dataset(db, dataset_id=dataset_id)
    if not db_dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    profile = MetadataService.get_profile(dataset_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Dataset profile not found in catalog cache")

    # --- Step 2: Save user message to chat history ---
    user_history_id = str(uuid.uuid4())
    db_user_msg = DBChatHistory(
        id=user_history_id,
        project_id=project_id,
        role="user",
        content=user_msg,
        type="text"
    )
    db.add(db_user_msg)
    db.commit()

    emit("classifying")
    # --- Step 3: Classify intent ---
    try:
        plan_response = QueryPlanner.plan_query(user_msg, profile)
        intent = plan_response.get("intent", "CONVERSATION")
    except Exception:
        intent = "CONVERSATION"

    # --- Step 4: Run the agent loop ---
    try:
        agent_result = Agent.run(
            user_query=user_msg,
            intent=intent,
            profile=profile,
            dataset_id=dataset_id,
            project_id=project_id,
            db=db,
            max_turns=5,
            emit=emit,
        )
    except Exception as e:
        agent_result = {
            "failed": True,
            "content": f"Agent encountered an error: {e}",
            "type": "text",
        }

    # --- Step 5: Save assistant response and return ---
    failed = agent_result.pop("failed", False)
    assistant_id = str(uuid.uuid4())
    content = agent_result.get("content", "")
    msg_type = agent_result.get("type", "text")

    # Build metadata from agent results (code, chart, raw data)
    metadata = {"question": user_msg, "user_message_id": user_history_id}
    if agent_result.get("calculation"):
        metadata["calculation"] = agent_result["calculation"]
    if agent_result.get("results"):
        metadata["results"] = agent_result["results"]
    if agent_result.get("code"):
        metadata["code"] = agent_result["code"]
    if agent_result.get("chart_base64"):
        metadata["chart_base64"] = agent_result["chart_base64"]

    db_assistant_msg = DBChatHistory(
        id=assistant_id,
        project_id=project_id,
        role="assistant",
        content=content,
        type=msg_type,
        metadata_json=json.dumps(metadata) if metadata else None,
    )
    db.add(db_assistant_msg)
    db.commit()

    return {
        "id": assistant_id,
        "role": "assistant",
        "content": content,
        "type": msg_type,
        "intent": intent,
        **{k: v for k, v in agent_result.items() if k not in ("content", "type")},
    }, failed
