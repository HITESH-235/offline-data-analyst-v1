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
import re
import copy
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
            emit('incomplete' if result.get('analysis_status')=='incomplete' else "failed" if failed else "completed", result=result)
        except HTTPException as error:
            emit("failed", error=error.detail)
        except Exception:
            emit("failed", error="The analyst could not finish the request.")

    async def stream():
        worker = asyncio.create_task(run_in_threadpool(run))
        while True:
            event = await events.get()
            yield json.dumps(event) + "\n"
            if event["stage"] in {"completed", "failed", 'incomplete'}:
                await worker
                return

    return StreamingResponse(stream(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def process_chat_message(request, db, emit):
    dataset_id = request.dataset_id
    project_id = request.project_id
    user_msg = request.message

    from app.services.project_service import ProjectService
    if not ProjectService.get_project(db, project_id):
        raise HTTPException(status_code=404, detail="Project not found")

    # Whole-database analysis needs a database-level context; table profiles
    # currently support only concrete table selections.
    if "::" not in dataset_id and dataset_id.lower().endswith((".db", ".sqlite")):
        raise HTTPException(
            status_code=400,
            detail="Analysis of a whole database is not supported yet. Select a table under the database in the sidebar, then ask your question. You can still ask to join it with other tables."
        )

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
    # Classification and table-selection failures terminate this request.
    # Never turn an unavailable model into a new conversation-mode model call.
    intent = None
    context_resolution=None
    completion_contract=None
    try:
        from app.services.analysis_context import load_context,grouping_update
        history=load_context(db,project_id)
        relevant=bool(history['recent_successes'])
        resolved_analysis=None
        resolved_tool=None
        execution_context=None
        execution_query=user_msg
        clarification=None
        from app.analysis.monthly_revenue import requested_year
        if requested_year(user_msg) is not None:
            intent = 'SIMPLE'
        else:
            plan_response = grouping_update(user_msg,history)
            if plan_response is None:
                plan_response=QueryPlanner.plan_query(user_msg, profile, analysis_context=history)
            intent = plan_response["intent"]
            if plan_response.get('completion_contract') is not None:
                from app.services.analysis_package import validate_requirements
                completion_contract=validate_requirements(plan_response['completion_contract'])
            operation=plan_response.get('operation') or {}
            if operation.get('type')=='comparison_summary':
                resolved_tool={'tool':'comparison_summary','parameters':operation.get('parameters',{})}
                if completion_contract is None:completion_contract={'outputs':[{'id':'comparison','kind':'comparison_summary'}]}
                intent='SIMPLE'
            action=plan_response.get('context_action','standalone')
            if action not in {'standalone','inherit','clarify'}:raise ValueError('Invalid analysis context action.')
            if action=='clarify':
                clarification=plan_response.get('clarification') or 'Which previous analysis and metric do you want to use?'
            elif action=='inherit':
                if not relevant:
                    clarification='Which analysis should I continue? Please name the metric and source.'
                else:
                    reference=plan_response.get('reference_message_id',history['recent_successes'][0]['message_id'])
                    selected=next((entry for entry in history['recent_successes'] if entry['message_id']==reference),None)
                    if selected is None:
                        raise ValueError('The referenced analysis is not in this project context. Please identify the intended analysis.')
                    execution_context={'recent_successes':[selected]}
                    context_resolution={'reference_message_id':reference,
                        'latest_success_message_id':history['recent_successes'][0]['message_id'],
                        'kind':plan_response.get('resolution_kind','semantic'),
                        'updated_fields':list((plan_response.get('resolved_analysis') or {}).keys())}
                    resolved_analysis=plan_response.get('resolved_analysis')
                    if resolved_analysis:
                        base=selected.get('analysis') or {'source':selected['source']}
                        resolved_analysis={**copy.deepcopy(base),**resolved_analysis}
                    elif plan_response.get('resolved_query'):
                        execution_query=plan_response['resolved_query']
                    else:
                        clarification='Which metric and grouping should I carry forward from the previous analysis?'
            else:
                resolved_analysis=plan_response.get('resolved_analysis')
                # A missing resolution must not turn a referential analysis into generic advice.
                if relevant and 'context_action' not in plan_response and re.search(r'\b(that|those|them|previous|same)\b',user_msg,re.I):
                    clarification='Which previous analysis should this refer to?'
            if resolved_analysis:
                intent='SIMPLE'
        if clarification:
            agent_result={'type':'text','content':clarification,'clarification_required':True}
        else:
            extra={}
            if execution_context or resolved_analysis:
                extra={'analysis_context':execution_context,'resolved_analysis':resolved_analysis}
            if resolved_tool:extra['resolved_tool']=resolved_tool
            if completion_contract:extra['completion_contract']=completion_contract
            agent_result = Agent.run(
                user_query=execution_query,
                intent=intent,
                profile=profile,
                dataset_id=dataset_id,
                project_id=project_id,
                db=db,
                max_turns=5,
                emit=emit,
                **extra,
            )
    except Exception as e:
        agent_result = {
            "failed": True,
            "content": f"Analysis stopped: {e}",
            "type": "text",
        }

    # --- Step 5: Save assistant response and return ---
    assistant_id = str(uuid.uuid4())
    if intent in {'SIMPLE','COMPLEX'} and not agent_result.get('clarification_required'):
        from app.services.analysis_package import finalize
        agent_result=finalize(agent_result,user_msg,project_id,assistant_id,completion_contract)
    elif intent=='CONVERSATION':agent_result['analysis_status']='not_applicable'
    failed = agent_result.pop("failed", False)
    content = agent_result.get("content", "")
    msg_type = agent_result.get("type", "text")

    # Build metadata from agent results (code, chart, raw data)
    metadata = {"question": user_msg, "user_message_id": user_history_id}
    metadata['analysis_failed']=failed
    if agent_result.get('analysis_package'):metadata['analysis_package']=agent_result['analysis_package']
    if agent_result.get('analysis_status'):metadata['analysis_status']=agent_result['analysis_status']
    if context_resolution:metadata['context_resolution']=context_resolution
    if not failed:
        from app.services.analysis_context import from_result
        context=from_result(agent_result)
        if context:metadata['analysis_context']=context
    if agent_result.get("calculation"):
        metadata["calculation"] = agent_result["calculation"]
    if agent_result.get("results"):
        metadata["results"] = agent_result["results"]
    if agent_result.get("code"):
        metadata["code"] = agent_result["code"]
    if agent_result.get("artifacts"):
        metadata["artifacts"] = agent_result["artifacts"]
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
        "question": user_msg,
        "role": "assistant",
        "content": content,
        "type": msg_type,
        "intent": intent,
        **{k: v for k, v in agent_result.items() if k not in ("content", "type")},
    }, failed
