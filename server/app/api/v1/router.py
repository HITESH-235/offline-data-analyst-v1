from fastapi import APIRouter
from app.api.v1.projects import router as projects_router
from app.api.v1.datasets import router as datasets_router
from app.api.v1.analysis import router as analysis_router
from app.api.v1.chat import router as chat_router

api_router = APIRouter()

api_router.include_router(projects_router)
api_router.include_router(datasets_router)
api_router.include_router(analysis_router)
api_router.include_router(chat_router)

@api_router.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "message": "Offline AI Data Analyst backend is running"}
