from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from firebase_admin_init import db
from dependencies import get_current_user
from datetime import datetime

router = APIRouter()

class ExpenseCreate(BaseModel):
    amount: float
    category_id: str

class Expense(BaseModel):
    id: str
    amount: float
    category_id: str
    category_name: str
    created_at: datetime

@router.post("/", response_model=Expense)
async def add_expense(
    expense: ExpenseCreate,
    current_user=Depends(get_current_user)
):
    category_ref = db.collection("expense_categories").document(expense.category_id)
    category_doc = category_ref.get()
    if not category_doc.exists or category_doc.to_dict().get("user_id") != current_user["uid"]:
        raise HTTPException(status_code=404, detail="Category not found")

    category_data = category_doc.to_dict()

    new_id = db.collection("expenses").document().id
    created_at = datetime.utcnow()

    new_expense = {
        "id": new_id,
        "amount": expense.amount,
        "category_id": expense.category_id,
        "created_at": created_at,
        "user_id": current_user["uid"],
    }
    db.collection("expenses").document(new_id).set(new_expense)

    return Expense(
        id=new_id,
        amount=expense.amount,
        category_id=expense.category_id,
        category_name=category_data["name"],
        created_at=created_at,
    )

@router.get("/", response_model=list[Expense])
async def list_expenses(current_user=Depends(get_current_user)):
    query = db.collection("expenses").where("user_id", "==", current_user["uid"]).stream()
    expenses = []

    for doc in query:
        data = doc.to_dict()
        category_doc = db.collection("expense_categories").document(data["category_id"]).get()
        category_name = category_doc.to_dict().get("name") if category_doc.exists else "Unknown"

        expenses.append(Expense(
            id=data["id"],
            amount=data["amount"],
            category_id=data["category_id"],
            category_name=category_name,
            created_at=data["created_at"],
        ))
    return expenses
