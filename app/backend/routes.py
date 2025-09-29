from fastapi import APIRouter
from .models import Data

router = APIRouter()

@router.get("/")
def root():
    return {"status": "FastAPI is running!"}

@router.post("/process")
def process(data: Data):
    return {"received": data.message.upper()}

