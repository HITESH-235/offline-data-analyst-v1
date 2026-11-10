"""Chat request boundary.

Resolve one complete typed plan, execute it through planned_analysis.run, and
publish once through analysis_package.finalize. Conversation and custom Python
are separate Agent routes. Persistence stays behind the request control fence.
"""

import asyncio
import json
import time
import uuid
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse, JSONResponse
import threading
from contextlib import nullcontext
from app.core.config import settings
from app.services.request_control import RequestControl, RequestStopped, current_request, checkpoint, terminal_stage, phase
from app.storage.sqlite.session import SessionLocal
from app.models.chat import ChatRequest, DBChatHistory
from app.services.dataset_manager import DatasetManager
from app.services.metadata_service import MetadataService
from app.llm.planner import QueryPlanner
from app.llm.agent import Agent

router = APIRouter(prefix="/chat", tags=["Chat"])


def stopped_result(control):
    return {"role": "assistant", "type": "text", "analysis_status": control.reason,
            "request_id": control.id,
            "content": "The analysis reached its request deadline. No result was published. Please try again." if control.reason == "timed_out" else "The analysis was cancelled. No result was published."}


async def supervised_events(request, control, connection=None):
    loop = asyncio.get_running_loop()
    events = asyncio.Queue()

    def emit(stage, **payload):
        control.stage(stage)
        event = {"stage": stage, "elapsed_ms": control.elapsed(), "request_id": control.id, **payload}
        try:
            loop.call_soon_threadsafe(events.put_nowait, event)
        except RuntimeError:
            control.stop('cancelled')

    control.progress = emit

    def run():
        token = current_request.set(control)
        try:
            with SessionLocal() as db:
                result, failed = process_chat_message(request, db, emit)
            # Publication sets outcome under the same fence as the DB commit.
            # The supervisor can observe it even if the worker is descheduled here.
            with control.lock:
                if control.outcome is None:
                    control.check()
                    control.outcome = (result, failed)
        except RequestStopped:
            pass
        except HTTPException as error:
            if not control.stopped.is_set():
                try: emit('failed', error=error.detail, status_code=error.status_code)
                except RequestStopped: pass
        except Exception:
            if not control.stopped.is_set():
                try: emit('failed', error='The analyst could not finish the request.')
                except RequestStopped: pass
        finally:
            current_request.reset(token)

    # A non-cooperative library cannot hold the response or executor shutdown open.
    threading.Thread(target=run, daemon=True, name='analysis-' + control.id).start()
    terminal = {'completed', 'failed', 'incomplete', 'clarification', 'unsupported'}
    last_heartbeat = time.monotonic()
    try:
        while True:
            if connection is not None and await connection.is_disconnected():
                control.stop('cancelled')
                return
            if control.outcome is not None:
                # Preserve ordered stage transitions even when finalization and
                # commit finish between supervisor polls.
                while not events.empty():
                    queued=events.get_nowait()
                    if queued['stage'] not in terminal:yield queued
                result, failed = control.outcome
                stage = terminal_stage(result, failed)
                with control.lock:
                    control.data.update(status=stage, elapsed_ms=control.elapsed())
                    control.persist()
                yield {'stage': stage, 'elapsed_ms': control.elapsed(), 'request_id': control.id, 'result': result}
                return
            remaining = control.deadline - time.monotonic()
            if remaining <= 0:
                control.stop('timed_out')
                yield {'stage': 'timed_out', 'elapsed_ms': control.elapsed(), 'result': stopped_result(control)}
                return
            try:
                event = await asyncio.wait_for(events.get(), min(remaining, 0.1))
            except asyncio.TimeoutError:
                if time.monotonic() - last_heartbeat >= 2:
                    last_heartbeat = time.monotonic()
                    stages = control.data['stages']
                    yield {'stage': stages[-1]['stage'] if stages else 'connecting',
                           'elapsed_ms': control.elapsed(), 'request_id': control.id, 'heartbeat': True}
                continue
            if control.stopped.is_set():
                return
            if event['stage'] in terminal:
                with control.lock:
                    control.data.update(status=event['stage'], elapsed_ms=control.elapsed())
                    control.persist()
                yield event
                return
            yield event
    finally:
        if not control.data.get('status'):
            control.stop('cancelled')


@router.post("/message", status_code=status.HTTP_200_OK)
async def handle_chat_message(request: ChatRequest, connection: Request = None):
    control = RequestControl(settings.CHAT_REQUEST_TIMEOUT_SECONDS)
    async for event in supervised_events(request, control, connection):
        if event['stage'] == 'timed_out':
            return JSONResponse(event['result'], status_code=504)
        if 'result' in event:
            return event['result']
        if 'error' in event:
            raise HTTPException(event.get('status_code', 500), event['error'])
    raise HTTPException(499, 'Request cancelled')


@router.post("/message/stream")
async def stream_chat_message(request: ChatRequest):
    control = RequestControl(settings.CHAT_REQUEST_TIMEOUT_SECONDS)

    async def stream():
        try:
            async for event in supervised_events(request, control):
                yield json.dumps(event) + "\n"
        finally:
            if not control.data.get('status'):
                control.stop('cancelled')

    # StreamingResponse cancels the iterator on disconnect, invoking its fence.
    return StreamingResponse(stream(), media_type="application/x-ndjson", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
        "X-Request-Timeout-Seconds": str(settings.CHAT_REQUEST_TIMEOUT_SECONDS)})


def process_chat_message(request, db, emit):
    control = current_request.get()
    original_emit = emit
    def emit(stage, **payload):
        checkpoint()
        original_emit(stage, **payload)
    checkpoint()
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
    planner_diagnostics=[]
    if control: control.data["planner_diagnostics"] = planner_diagnostics
    requested_analysis=None
    try:
        from app.services.analysis_context import load_context
        from app.services.request_requirements import validate_structured_plan
        from app.services.planned_analysis import run, validate_context
        history=load_context(db,project_id)
        with phase('planning'):
            plan_response=QueryPlanner.plan_query(user_msg,{**profile,'dataset_id':dataset_id},
                analysis_context=history,diagnostics=planner_diagnostics)
        checkpoint()
        from app.analysis.operations import validate_plan
        plan_response=validate_plan(plan_response,history=history)
        intent=plan_response['intent']
        requested_analysis=plan_response.get('analysis_plan')
        action=plan_response.get('context_action','standalone')
        if action=='clarify':
            agent_result={'type':'text','content':plan_response.get('clarification') or 'Please clarify the calculation and source.',
                          'clarification_required':True,'analysis_status':'clarification'}
        elif plan_response.get('unsupported_reason'):
            agent_result={'failed':True,'unsupported':True,'analysis_status':'unsupported','type':'text',
                          'content':plan_response['unsupported_reason']}
        elif intent=='SIMPLE':
            if not requested_analysis:
                from app.services.request_requirements import RequestIncomplete
                raise RequestIncomplete('No complete typed analysis plan was provided. No substitute calculation was run.')
            if action=='inherit':
                reference=plan_response.get('reference_message_id')
                validate_context(requested_analysis,history,reference=reference,changed_fields=plan_response.get('changed_fields',[]))
                context_resolution={'reference_message_id':reference,
                    'updated_fields':plan_response.get('changed_fields',[])}
            agent_result,completion_contract=run(requested_analysis,db,emit)
            agent_result['analysis_plan']=requested_analysis
        else:
            # Conversation and custom Python never substitute for a missing
            # deterministic plan. Python keeps its independent export verifier.
            if intent=='COMPLEX':
                from app.services.request_requirements import validate_structured_plan
                completion_contract=plan_response.get('request_requirements')
                validate_structured_plan(plan_response,completion_contract or {})
            agent_result=Agent.run(user_query=user_msg,intent=intent,profile=profile,
                dataset_id=dataset_id,project_id=project_id,db=db,max_turns=5,emit=emit,
                **({"completion_contract":completion_contract} if completion_contract else {}))
    except Exception as e:
        from app.analysis.operations import ContractError
        from app.services.output_identity import OutputIdentityError
        from app.services.planned_analysis import UnsupportedOperation
        from app.services.request_requirements import RequestIncomplete
        plan_rejection=isinstance(e,ContractError) or bool(planner_diagnostics and not planner_diagnostics[-1].get('accepted'))
        validation_error=(planner_diagnostics[-1]['error'] if plan_rejection and planner_diagnostics and not planner_diagnostics[-1].get('accepted') else str(e))
        if isinstance(e,RequestIncomplete) or plan_rejection:intent="SIMPLE"
        agent_result = {
            "failed": True,
            **({"clarification_required":True,"analysis_status":"clarification"} if isinstance(e,OutputIdentityError) else {}),
            **({"request_incomplete":True,"validation_error":validation_error} if isinstance(e,RequestIncomplete) or plan_rejection else {}),
            "content": (str(e) if isinstance(e,(UnsupportedOperation,RequestIncomplete)) else
                        'Plan validation stopped before calculation: '+validation_error
                        if plan_rejection else f"Analysis stopped: {e}"),
            "type": "text",
            **({"unsupported":True,"analysis_status":"unsupported"} if isinstance(e,UnsupportedOperation) else {}),
        }

    checkpoint()
    emit("validating")
    # --- Step 5: Save assistant response and return ---
    assistant_id = str(uuid.uuid4())
    if intent in {'SIMPLE','COMPLEX'} and not agent_result.get('clarification_required') and not agent_result.get('unsupported'):
        from app.services.analysis_package import finalize
        with phase("publication_verification"):
            agent_result=finalize(agent_result,user_msg,project_id,assistant_id,completion_contract)
    elif intent=='CONVERSATION':agent_result['analysis_status']='not_applicable'
    failed = agent_result.pop("failed", False)
    content = agent_result.get("content", "")
    msg_type = agent_result.get("type", "text")

    emit("preparing_answer")
    # Build metadata from agent results (code, chart, raw data)
    metadata = {"question": user_msg, "user_message_id": user_history_id}
    if control:
        metadata.update(request_id=control.id, request_stage=terminal_stage(agent_result, failed),
                        elapsed_ms=control.elapsed())
    if planner_diagnostics:
        metadata['planner_diagnostics']=planner_diagnostics
        agent_result['planner_diagnostics']=planner_diagnostics
    if requested_analysis:
        from app.analysis.operations import sanitize
        metadata['requested_analysis']=sanitize(requested_analysis)
    metadata['analysis_failed']=failed
    if failed or agent_result.get('clarification_required'):
        metadata['unresolved_intent']={'question':user_msg,'plan':requested_analysis,
            **({'requirements':completion_contract} if intent=='COMPLEX' else {})}
    if agent_result.get('analysis_package'):metadata['analysis_package']=agent_result['analysis_package']
    if agent_result.get('analysis_status'):metadata['analysis_status']=agent_result['analysis_status']
    if agent_result.get('scalar_answer'):metadata['scalar_answer']=True
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
    response = {
        "id": assistant_id,
        "question": user_msg,
        "role": "assistant",
        "content": content,
        "type": msg_type,
        "intent": intent,
        "request_stage": terminal_stage(agent_result, failed),
        **({"elapsed_ms": control.elapsed()} if control else {}),
        **{k: v for k, v in agent_result.items() if k not in ("content", "type")},
    }
    # Potentially slow inserts/lock acquisition stay outside the publication fence.
    # If they outlive the budget, SessionLocal rolls back the uncommitted row.
    emit("publishing")
    db.add(db_assistant_msg)
    db.flush()
    with control.publication() if control else nullcontext():
        db.commit()
        if control:
            control.outcome = (response, failed)
            control.data['published_ms'] = control.elapsed()
    return response, failed
