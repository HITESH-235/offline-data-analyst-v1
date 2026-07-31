import uvicorn # used to run and host fastapi
from fastapi import FastAPI # framework for making the backend api
from fastapi.middleware.cors import CORSMiddleware # allows react to query the server (cross origin)
from app.core.config import settings, setup_logging # imports the settiings of log info
from app.storage.sqlite.session import Base, engine
from app.models.project import DBProject
from app.models.dataset import DBDataset
from app.models.chat import DBChatHistory
from app.api.v1.router import api_router

# Create DB tables if they don't exist
Base.metadata.create_all(bind=engine)

# Setup logging configuration
setup_logging()

app = FastAPI( # instantiate the fastapi app
    title=settings.APP_NAME,
    description="Offline AI Data Analyst Backend Engine (V1)",
    version="1.0.0",
    debug=settings.DEBUG
)

@app.on_event("startup")
def startup_scan_catalog():
    from app.services.metadata_service import MetadataService
    MetadataService.scan_and_profile_catalog()

# Enable CORS for local React development (allows react to query)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # allows all origins
    allow_credentials=True,
    allow_methods=["*"], # allows all methods (GET, POST, DELETE, UPDATE, etc.)
    allow_headers=["*"], # allows all headers
)

# Register API v1 router
app.include_router(api_router, prefix="/api/v1")

@app.get("/") # root endpoint
async def root():
    return {
        "message": f"Welcome to {settings.APP_NAME}",
        "docs_url": "/docs",
        "health_check": "/api/v1/health"
    }

if __name__ == "__main__":
    uvicorn.run( # instantiating the uvicorn server to run the fastapi app
        "main:app", # specifies the app to run
        host=settings.HOST, # host to run on
        port=settings.PORT, # port to run on
        reload=settings.DEBUG # reloads server when code changes
    )
