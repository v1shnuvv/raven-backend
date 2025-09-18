from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from firebase_admin_init import db
from dependencies import get_current_user

router = APIRouter()

class ActivityCreate(BaseModel):
    name: str

class Activity(BaseModel):
    id: str
    name: str

@router.post("/", response_model=Activity)
async def add_activity(
    activity: ActivityCreate,
    current_user=Depends(get_current_user)
):
    doc_ref = db.collection("activities").document()
    data = {
        "id": doc_ref.id,
        "name": activity.name,
        "user_id": current_user["uid"]
    }
    doc_ref.set(data)
    return Activity(id=doc_ref.id, name=activity.name)

@router.get("/", response_model=list[Activity])
async def list_activities(current_user=Depends(get_current_user)):
    query = db.collection("activities").where("user_id", "==", current_user["uid"]).stream()
    activities = []
    for doc in query:
        d = doc.to_dict()
        activities.append(Activity(id=d["id"], name=d["name"]))
    return activities
