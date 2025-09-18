from fastapi import APIRouter, Depends
from pydantic import BaseModel
from firebase_admin_init import db
from dependencies import get_current_user

router = APIRouter()

class ExpenseCategoryCreate(BaseModel):
    name: str

class ExpenseCategory(BaseModel):
    id: str
    name: str

@router.post("/", response_model=ExpenseCategory)
async def add_category(
    category: ExpenseCategoryCreate,
    current_user=Depends(get_current_user)
):
    doc_ref = db.collection("expense_categories").document()
    data = {
        "id": doc_ref.id,
        "name": category.name,
        "user_id": current_user["uid"]
    }
    doc_ref.set(data)
    return ExpenseCategory(id=doc_ref.id, name=category.name)

@router.get("/", response_model=list[ExpenseCategory])
async def list_categories(current_user=Depends(get_current_user)):
    query = db.collection("expense_categories").where("user_id", "==", current_user["uid"]).stream()
    categories = []
    for doc in query:
        d = doc.to_dict()
        categories.append(ExpenseCategory(id=d["id"], name=d["name"]))
    return categories
