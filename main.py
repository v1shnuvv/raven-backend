from fastapi import FastAPI
from routers import activities, time_entries, expense_categories, expenses
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# origins = [
#     "http://localhost:5173",  
#     "http://127.0.0.1:5173"
# ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(activities.router, prefix="/activities", tags=["activities"])
app.include_router(time_entries.router, prefix="/time_entries", tags=["time_entries"])
app.include_router(expense_categories.router, prefix="/expense_categories", tags=["expense_categories"])
app.include_router(expenses.router, prefix="/expenses", tags=["expenses"])
