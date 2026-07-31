from datetime import datetime
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, String, DateTime, ForeignKey
from app.storage.sqlite.session import Base
from typing import Optional, Dict, Any

# --- SQLAlchemy Table Model ---
class DBChatHistory(Base):
    __tablename__ = "chat_history"
    
    id = Column(String, primary_key=True, index=True)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)  # "user" or "assistant"
    content = Column(String, nullable=False)
    type = Column(String, default="text")  # "text", "plan", "code", "table", "chart"
    metadata_json = Column(String, nullable=True)  # Store JSON representation of plans/code traces
    created_at = Column(DateTime, default=datetime.utcnow)


# --- Pydantic Data Schemas ---
class ChatMessageBase(BaseModel): # base model for all chat message related schemas
    role: str
    content: str
    type: str = "text"
    metadata_json: Optional[str] = None  # store json representation of plans/code traces

class ChatMessageCreate(ChatMessageBase): # create model for new chat message
    pass

class ChatMessage(ChatMessageBase): # output model represent. complete message stored in db
    id: str
    project_id: str
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class ChatRequest(BaseModel): # used when user sends chat message (to backend)
    project_id: str
    dataset_id: str
    message: str
