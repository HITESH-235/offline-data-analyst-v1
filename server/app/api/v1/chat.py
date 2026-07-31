"""
Chat endpoint — simplified to use the Agent loop.

Flow:
  1. Validate dataset exists
  2. Log user message to DB
  3. Classify intent using QueryPlanner
  4. Run Agent.run() with the classified intent
  5. Save assistant response to DB and return
"""

import json
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.storage.sqlite.session import get_db
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
        )
    except Exception as e:
        agent_result = {
            "content": f"Agent encountered an error: {e}",
            "type": "text",
        }

    # --- Step 5: Save assistant response and return ---
    assistant_id = str(uuid.uuid4())
    content = agent_result.get("content", "")
    msg_type = agent_result.get("type", "text")

    # Build metadata from agent results (code, chart, raw data)
    metadata = {}
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
    }
