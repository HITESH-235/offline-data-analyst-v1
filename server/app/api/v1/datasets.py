from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.storage.sqlite.session import get_db
from app.models.dataset import Dataset, DatasetPreview
from app.services.dataset_manager import DatasetManager

router = APIRouter(prefix="/datasets", tags=["Datasets"])

@router.get("", response_model=List[Dataset])
@router.get("/catalog", response_model=List[Dataset])
@router.get("/project/{project_id}", response_model=List[Dataset])
def list_catalog_datasets(project_id: str = "catalog", db: Session = Depends(get_db)):
    """
    Returns pre-loaded catalog datasets from the fixed datasets/ directory.
    """
    return DatasetManager.get_catalog_datasets()

@router.get("/{dataset_id}/preview", response_model=DatasetPreview)
def get_dataset_preview(dataset_id: str, db: Session = Depends(get_db)):
    db_dataset = DatasetManager.get_dataset(db, dataset_id=dataset_id)
    if not db_dataset:
        raise HTTPException(status_code=404, detail="Dataset not found in catalog")
    try:
        return DatasetManager.get_preview(db_dataset)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read dataset: {e}")

@router.get("/{dataset_id}/profile")
def get_dataset_profile(dataset_id: str, db: Session = Depends(get_db)):
    from app.services.metadata_service import MetadataService
    profile = MetadataService.get_profile(dataset_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Dataset profile not found in catalog cache")
    return profile
