from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date, timedelta
import re
from google.cloud.firestore_v1.base_query import FieldFilter
import pytz

from firebase_admin_init import db
from dependencies import get_current_user

router = APIRouter()

class ActivityCreate(BaseModel):
    name: str
    description: Optional[str] = None

class Activity(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    user_id: str
    created_at: Optional[datetime] = None 

class Note(BaseModel):
    id: str
    content: str
    created_at: datetime

class TimeEntryCreate(BaseModel):
    activity_id: str
    start_datetime: datetime
    end_datetime: Optional[datetime] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = []

class TimeEntryUpdate(BaseModel):
    end_datetime: Optional[datetime] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None

class TimeEntry(BaseModel):
    id: str
    activity_id: str
    activity_name: str
    start_datetime: datetime
    end_datetime: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    notes: Optional[str] = None
    tags: List[str] = []
    is_running: bool = False
    created_at: datetime

class TimeEntryWithTotal(BaseModel):
    entries: List[TimeEntry]
    total_minutes: int
    total_hours: float

def extract_tags_from_text(text: str) -> tuple[str, List[str]]:
    """Extract hashtags from text and return clean text and tags list"""
    if not text:
        return "", []
    
    hashtag_pattern = r'#(\w+)'
    tags = re.findall(hashtag_pattern, text)
    
    clean_text = re.sub(hashtag_pattern, '', text).strip()
    clean_text = ' '.join(clean_text.split())
    
    return clean_text, tags

def get_utc_datetime(dt: datetime) -> datetime:
    """Convert datetime to UTC timezone-aware datetime"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=pytz.UTC)
    return dt.astimezone(pytz.UTC)

def get_date_range(target_date: date) -> tuple[datetime, datetime]:
    """Get start and end of day in UTC for a given date"""
    start_of_day = datetime.combine(target_date, datetime.min.time())
    end_of_day = datetime.combine(target_date, datetime.max.time())
    return get_utc_datetime(start_of_day), get_utc_datetime(end_of_day)
    """Calculate duration in minutes between start and end datetime"""
    if not end_dt:
        return None
    
    if start_dt.tzinfo is None and end_dt.tzinfo is not None:
        start_dt = start_dt.replace(tzinfo=pytz.UTC)
    elif start_dt.tzinfo is not None and end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=pytz.UTC)
    elif start_dt.tzinfo is None and end_dt.tzinfo is None:
        pass
    
    return int((end_dt - start_dt).total_seconds() / 60)

def calculate_duration(start_dt, end_dt):
    if start_dt.tzinfo is None and end_dt.tzinfo is not None:
        start_dt = start_dt.replace(tzinfo=pytz.UTC)
    return int((end_dt - start_dt).total_seconds() / 60)  # ✅


@router.post("/activities", response_model=Activity)
async def create_activity(
    activity: ActivityCreate,
    current_user=Depends(get_current_user)
):
    """Create a new activity"""
    new_id = db.collection("activities").document().id
    created_at = datetime.utcnow()
    
    new_activity = {
        "id": new_id,
        "name": activity.name,
        "description": activity.description,
        "user_id": current_user["uid"],
        "created_at": created_at,
    }
    
    db.collection("activities").document(new_id).set(new_activity)
    
    return Activity(**new_activity)

@router.get("/activities", response_model=List[Activity])
async def list_activities(current_user=Depends(get_current_user)):
    """List all activities for the current user"""
    docs = db.collection("activities").where(filter=FieldFilter("user_id", "==", current_user["uid"])).stream()
    activities = []
    
    for doc in docs:
        activity_data = doc.to_dict()
        if 'created_at' not in activity_data:
            activity_data['created_at'] = datetime.utcnow()
        activities.append(Activity(**activity_data))
    
    return activities

@router.post("/", response_model=TimeEntry)
async def add_time_entry(
    entry: TimeEntryCreate,
    current_user=Depends(get_current_user)
):
    """Add time entry with start datetime and optional end datetime"""
    activity_ref = db.collection("activities").document(entry.activity_id)
    activity_doc = activity_ref.get()
    if not activity_doc.exists or activity_doc.to_dict().get("user_id") != current_user["uid"]:
        raise HTTPException(status_code=404, detail="Activity not found")

    activity_data = activity_doc.to_dict()
    new_id = db.collection("time_entries").document().id
    created_at = datetime.utcnow().replace(tzinfo=pytz.UTC)

    clean_notes, extracted_tags = extract_tags_from_text(entry.notes or "")
    all_tags = list(set((entry.tags or []) + extracted_tags))

    start_datetime = entry.start_datetime
    end_datetime = entry.end_datetime
    
    if hasattr(start_datetime, 'tzinfo') and start_datetime.tzinfo is None:
        start_datetime = start_datetime.replace(tzinfo=pytz.UTC)
    if end_datetime and hasattr(end_datetime, 'tzinfo') and end_datetime.tzinfo is None:
        end_datetime = end_datetime.replace(tzinfo=pytz.UTC)

    duration_minutes = calculate_duration(start_datetime, end_datetime)
    is_running = end_datetime is None

    new_entry = {
        "id": new_id,
        "activity_id": entry.activity_id,
        "start_datetime": start_datetime,
        "end_datetime": end_datetime,
        "duration_minutes": duration_minutes,
        "notes": clean_notes if clean_notes else None,
        "tags": all_tags,
        "is_running": is_running,
        "created_at": created_at,
        "user_id": current_user["uid"],
    }
    
    db.collection("time_entries").document(new_id).set(new_entry)

    return TimeEntry(
        id=new_id,
        activity_id=entry.activity_id,
        activity_name=activity_data.get("name", "Unknown"),
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        duration_minutes=duration_minutes,
        notes=clean_notes if clean_notes else None,
        tags=all_tags,
        is_running=is_running,
        created_at=created_at,
    )

@router.post("/start/{activity_id}", response_model=TimeEntry)
async def start_time_entry(
    activity_id: str,
    current_user=Depends(get_current_user)
):
    """Start a time entry by clicking play button (current datetime as start)"""
    activity_ref = db.collection("activities").document(activity_id)
    activity_doc = activity_ref.get()
    if not activity_doc.exists or activity_doc.to_dict().get("user_id") != current_user["uid"]:
        raise HTTPException(status_code=404, detail="Activity not found")

    activity_data = activity_doc.to_dict()
    
    running_entries = db.collection("time_entries").where(filter=FieldFilter("user_id", "==", current_user["uid"])).where(filter=FieldFilter("is_running", "==", True)).stream()
    if any(running_entries):
        raise HTTPException(status_code=400, detail="Another time entry is already running. Please stop it first.")

    new_id = db.collection("time_entries").document().id
    current_time = datetime.utcnow().replace(tzinfo=pytz.UTC)

    new_entry = {
        "id": new_id,
        "activity_id": activity_id,
        "start_datetime": current_time,
        "end_datetime": None,
        "duration_minutes": None,
        "notes": None,
        "tags": [],
        "is_running": True,
        "created_at": current_time,
        "user_id": current_user["uid"],
    }
    
    db.collection("time_entries").document(new_id).set(new_entry)

    return TimeEntry(
        id=new_id,
        activity_id=activity_id,
        activity_name=activity_data.get("name", "Unknown"),
        start_datetime=current_time,
        end_datetime=None,
        duration_minutes=None,
        notes=None,
        tags=[],
        is_running=True,
        created_at=current_time,
    )

@router.patch("/{entry_id}/stop", response_model=TimeEntry)
async def stop_time_entry(
    entry_id: str,
    current_user=Depends(get_current_user)
):
    """Stop a running time entry by clicking pause button"""
    entry_ref = db.collection("time_entries").document(entry_id)
    entry_doc = entry_ref.get()
    
    if not entry_doc.exists:
        raise HTTPException(status_code=404, detail="Time entry not found")
    
    entry_data = entry_doc.to_dict()
    
    if entry_data.get("user_id") != current_user["uid"]:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if not entry_data.get("is_running", False):
        raise HTTPException(status_code=400, detail="Time entry is not running")

    current_time = datetime.utcnow().replace(tzinfo=pytz.UTC)
    
    start_datetime = entry_data["start_datetime"]
    if hasattr(start_datetime, 'tzinfo') and start_datetime.tzinfo is None:
        start_datetime = start_datetime.replace(tzinfo=pytz.UTC)
    
    duration_minutes = calculate_duration(start_datetime, current_time)
    
    updates = {
        "end_datetime": current_time,
        "duration_minutes": duration_minutes,
        "is_running": False,
    }
    
    entry_ref.update(updates)
    
    activity_ref = db.collection("activities").document(entry_data["activity_id"])
    activity_doc = activity_ref.get()
    activity_name = activity_doc.to_dict().get("name") if activity_doc.exists else "Unknown"

    return TimeEntry(
        id=entry_id,
        activity_id=entry_data["activity_id"],
        activity_name=activity_name,
        start_datetime=entry_data["start_datetime"],
        end_datetime=current_time,
        duration_minutes=duration_minutes,
        notes=entry_data.get("notes"),
        tags=entry_data.get("tags", []),
        is_running=False,
        created_at=entry_data["created_at"],
    )

@router.patch("/{entry_id}", response_model=TimeEntry)
async def update_time_entry(
    entry_id: str,
    update_data: TimeEntryUpdate,
    current_user=Depends(get_current_user)
):
    """Update time entry - add/edit notes, end datetime, or tags"""
    entry_ref = db.collection("time_entries").document(entry_id)
    entry_doc = entry_ref.get()
    
    if not entry_doc.exists:
        raise HTTPException(status_code=404, detail="Time entry not found")
    
    entry_data = entry_doc.to_dict()
    
    if entry_data.get("user_id") != current_user["uid"]:
        raise HTTPException(status_code=403, detail="Access denied")

    updates = {}
    
    if update_data.notes is not None:
        clean_notes, extracted_tags = extract_tags_from_text(update_data.notes)
        updates["notes"] = clean_notes if clean_notes else None
        
        existing_tags = entry_data.get("tags", [])
        new_tags = update_data.tags or []
        all_tags = list(set(existing_tags + new_tags + extracted_tags))
        updates["tags"] = all_tags
    elif update_data.tags is not None:
        updates["tags"] = update_data.tags
    
    if update_data.end_datetime is not None:
        end_datetime = update_data.end_datetime
        start_datetime = entry_data["start_datetime"]
        
        if hasattr(start_datetime, 'tzinfo') and start_datetime.tzinfo is None:
            start_datetime = start_datetime.replace(tzinfo=pytz.UTC)
        if hasattr(end_datetime, 'tzinfo') and end_datetime.tzinfo is None:
            end_datetime = end_datetime.replace(tzinfo=pytz.UTC)
            
        duration_minutes = calculate_duration(start_datetime, end_datetime)
        updates.update({
            "end_datetime": end_datetime,
            "duration_minutes": duration_minutes,
            "is_running": False,
        })
    
    if updates:
        entry_ref.update(updates)
        entry_data.update(updates)
    
    activity_ref = db.collection("activities").document(entry_data["activity_id"])
    activity_doc = activity_ref.get()
    activity_name = activity_doc.to_dict().get("name") if activity_doc.exists else "Unknown"

    return TimeEntry(
        id=entry_id,
        activity_id=entry_data["activity_id"],
        activity_name=activity_name,
        start_datetime=entry_data["start_datetime"],
        end_datetime=entry_data.get("end_datetime"),
        duration_minutes=entry_data.get("duration_minutes"),
        notes=entry_data.get("notes"),
        tags=entry_data.get("tags", []),
        is_running=entry_data.get("is_running", False),
        created_at=entry_data["created_at"],
    )


@router.get("/", response_model=TimeEntryWithTotal)
async def list_time_entries(
    activity_id: Optional[str] = Query(None),
    current_user=Depends(get_current_user)
):
    """View all time entries"""
    query = db.collection("time_entries").where(filter=FieldFilter("user_id", "==", current_user["uid"]))
    if activity_id:
        query = query.where(filter=FieldFilter("activity_id", "==", activity_id))

    docs = query.order_by("start_datetime", direction="DESCENDING").stream()
    entries = []
    total_minutes = 0

    for doc in docs:
        entry_data = doc.to_dict()

        activity_ref = db.collection("activities").document(entry_data["activity_id"])
        activity_doc = activity_ref.get()
        activity_name = activity_doc.to_dict().get("name") if activity_doc.exists else "Unknown"

        time_entry = TimeEntry(
            id=entry_data["id"],
            activity_id=entry_data["activity_id"],
            activity_name=activity_name,
            start_datetime=entry_data["start_datetime"],
            end_datetime=entry_data.get("end_datetime"),
            duration_minutes=entry_data.get("duration_minutes"),
            notes=entry_data.get("notes"),
            tags=entry_data.get("tags", []),
            is_running=entry_data.get("is_running", False),
            created_at=entry_data["created_at"],
        )
        
        entries.append(time_entry)
        
        if entry_data.get("duration_minutes"):
            total_minutes += entry_data["duration_minutes"]

    return TimeEntryWithTotal(
        entries=entries,
        total_minutes=total_minutes,
        total_hours=round(total_minutes / 60, 2)
    )

@router.get("/today", response_model=TimeEntryWithTotal)
async def get_today_entries(current_user=Depends(get_current_user)):
    """View today's time entries"""
    today = date.today()
    start_of_day, end_of_day = get_date_range(today)
    
    docs = db.collection("time_entries")\
        .where(filter=FieldFilter("user_id", "==", current_user["uid"]))\
        .where(filter=FieldFilter("start_datetime", ">=", start_of_day))\
        .where(filter=FieldFilter("start_datetime", "<=", end_of_day))\
        .order_by("start_datetime", direction="DESCENDING")\
        .stream()
    
    entries = []
    total_minutes = 0

    for doc in docs:
        entry_data = doc.to_dict()

        activity_ref = db.collection("activities").document(entry_data["activity_id"])
        activity_doc = activity_ref.get()
        activity_name = activity_doc.to_dict().get("name") if activity_doc.exists else "Unknown"

        time_entry = TimeEntry(
            id=entry_data["id"],
            activity_id=entry_data["activity_id"],
            activity_name=activity_name,
            start_datetime=entry_data["start_datetime"],
            end_datetime=entry_data.get("end_datetime"),
            duration_minutes=entry_data.get("duration_minutes"),
            notes=entry_data.get("notes"),
            tags=entry_data.get("tags", []),
            is_running=entry_data.get("is_running", False),
            created_at=entry_data["created_at"],
        )
        
        entries.append(time_entry)
        
        if entry_data.get("duration_minutes"):
            total_minutes += entry_data["duration_minutes"]

    return TimeEntryWithTotal(
        entries=entries,
        total_minutes=total_minutes,
        total_hours=round(total_minutes / 60, 2)
    )

@router.get("/date/{selected_date}", response_model=TimeEntryWithTotal)
async def get_date_entries(
    selected_date: date,
    current_user=Depends(get_current_user)
):
    """View time entries for a selected date"""
    start_of_day, end_of_day = get_date_range(selected_date)
    
    docs = db.collection("time_entries")\
        .where(filter=FieldFilter("user_id", "==", current_user["uid"]))\
        .where(filter=FieldFilter("start_datetime", ">=", start_of_day))\
        .where(filter=FieldFilter("start_datetime", "<=", end_of_day))\
        .order_by("start_datetime", direction="DESCENDING")\
        .stream()
    
    entries = []
    total_minutes = 0

    for doc in docs:
        entry_data = doc.to_dict()

        activity_ref = db.collection("activities").document(entry_data["activity_id"])
        activity_doc = activity_ref.get()
        activity_name = activity_doc.to_dict().get("name") if activity_doc.exists else "Unknown"

        time_entry = TimeEntry(
            id=entry_data["id"],
            activity_id=entry_data["activity_id"],
            activity_name=activity_name,
            start_datetime=entry_data["start_datetime"],
            end_datetime=entry_data.get("end_datetime"),
            duration_minutes=entry_data.get("duration_minutes"),
            notes=entry_data.get("notes"),
            tags=entry_data.get("tags", []),
            is_running=entry_data.get("is_running", False),
            created_at=entry_data["created_at"],
        )
        
        entries.append(time_entry)
        
        if entry_data.get("duration_minutes"):
            total_minutes += entry_data["duration_minutes"]

    return TimeEntryWithTotal(
        entries=entries,
        total_minutes=total_minutes,
        total_hours=round(total_minutes / 60, 2)
    )

@router.get("/month", response_model=TimeEntryWithTotal)
async def get_this_month_entries(current_user=Depends(get_current_user)):
    """View this month's time entries"""
    today = date.today()
    start_of_month = datetime.combine(today.replace(day=1), datetime.min.time())
    start_of_month = get_utc_datetime(start_of_month)
    
    if today.month == 12:
        end_of_month = datetime.combine(today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1), datetime.max.time())
    else:
        end_of_month = datetime.combine(today.replace(month=today.month + 1, day=1) - timedelta(days=1), datetime.max.time())
    end_of_month = get_utc_datetime(end_of_month)
    
    docs = db.collection("time_entries")\
        .where(filter=FieldFilter("user_id", "==", current_user["uid"]))\
        .where(filter=FieldFilter("start_datetime", ">=", start_of_month))\
        .where(filter=FieldFilter("start_datetime", "<=", end_of_month))\
        .order_by("start_datetime", direction="DESCENDING")\
        .stream()
    
    entries = []
    total_minutes = 0

    for doc in docs:
        entry_data = doc.to_dict()

        activity_ref = db.collection("activities").document(entry_data["activity_id"])
        activity_doc = activity_ref.get()
        activity_name = activity_doc.to_dict().get("name") if activity_doc.exists else "Unknown"

        time_entry = TimeEntry(
            id=entry_data["id"],
            activity_id=entry_data["activity_id"],
            activity_name=activity_name,
            start_datetime=entry_data["start_datetime"],
            end_datetime=entry_data.get("end_datetime"),
            duration_minutes=entry_data.get("duration_minutes"),
            notes=entry_data.get("notes"),
            tags=entry_data.get("tags", []),
            is_running=entry_data.get("is_running", False),
            created_at=entry_data["created_at"],
        )
        
        entries.append(time_entry)
        
        if entry_data.get("duration_minutes"):
            total_minutes += entry_data["duration_minutes"]

    return TimeEntryWithTotal(
        entries=entries,
        total_minutes=total_minutes,
        total_hours=round(total_minutes / 60, 2)
    )

@router.get("/year", response_model=TimeEntryWithTotal)
async def get_this_year_entries(current_user=Depends(get_current_user)):
    """View this year's time entries"""
    today = date.today()
    start_of_year = datetime.combine(today.replace(month=1, day=1), datetime.min.time())
    end_of_year = datetime.combine(today.replace(month=12, day=31), datetime.max.time())
    start_of_year = get_utc_datetime(start_of_year)
    end_of_year = get_utc_datetime(end_of_year)
    
    docs = db.collection("time_entries")\
        .where(filter=FieldFilter("user_id", "==", current_user["uid"]))\
        .where(filter=FieldFilter("start_datetime", ">=", start_of_year))\
        .where(filter=FieldFilter("start_datetime", "<=", end_of_year))\
        .order_by("start_datetime", direction="DESCENDING")\
        .stream()
    
    entries = []
    total_minutes = 0

    for doc in docs:
        entry_data = doc.to_dict()

        activity_ref = db.collection("activities").document(entry_data["activity_id"])
        activity_doc = activity_ref.get()
        activity_name = activity_doc.to_dict().get("name") if activity_doc.exists else "Unknown"

        time_entry = TimeEntry(
            id=entry_data["id"],
            activity_id=entry_data["activity_id"],
            activity_name=activity_name,
            start_datetime=entry_data["start_datetime"],
            end_datetime=entry_data.get("end_datetime"),
            duration_minutes=entry_data.get("duration_minutes"),
            notes=entry_data.get("notes"),
            tags=entry_data.get("tags", []),
            is_running=entry_data.get("is_running", False),
            created_at=entry_data["created_at"],
        )
        
        entries.append(time_entry)
        
        if entry_data.get("duration_minutes"):
            total_minutes += entry_data["duration_minutes"]

    return TimeEntryWithTotal(
        entries=entries,
        total_minutes=total_minutes,
        total_hours=round(total_minutes / 60, 2)
    )

@router.get("/tags/{tag}", response_model=TimeEntryWithTotal)
async def get_entries_by_tag(
    tag: str,
    current_user=Depends(get_current_user)
):
    """View time entries filtered by tag with total time spent"""
    docs = db.collection("time_entries")\
        .where(filter=FieldFilter("user_id", "==", current_user["uid"]))\
        .where(filter=FieldFilter("tags", "array_contains", tag))\
        .order_by("start_datetime", direction="DESCENDING")\
        .stream()
    
    entries = []
    total_minutes = 0

    for doc in docs:
        entry_data = doc.to_dict()

        activity_ref = db.collection("activities").document(entry_data["activity_id"])
        activity_doc = activity_ref.get()
        activity_name = activity_doc.to_dict().get("name") if activity_doc.exists else "Unknown"

        time_entry = TimeEntry(
            id=entry_data["id"],
            activity_id=entry_data["activity_id"],
            activity_name=activity_name,
            start_datetime=entry_data["start_datetime"],
            end_datetime=entry_data.get("end_datetime"),
            duration_minutes=entry_data.get("duration_minutes"),
            notes=entry_data.get("notes"),
            tags=entry_data.get("tags", []),
            is_running=entry_data.get("is_running", False),
            created_at=entry_data["created_at"],
        )
        
        entries.append(time_entry)
        
        if entry_data.get("duration_minutes"):
            total_minutes += entry_data["duration_minutes"]

    return TimeEntryWithTotal(
        entries=entries,
        total_minutes=total_minutes,
        total_hours=round(total_minutes / 60, 2)
    )

@router.get("/running", response_model=List[TimeEntry])
async def get_running_entries(current_user=Depends(get_current_user)):
    """Get all currently running time entries for the user"""
    docs = db.collection("time_entries")\
        .where(filter=FieldFilter("user_id", "==", current_user["uid"]))\
        .where(filter=FieldFilter("is_running", "==", True))\
        .stream()
    
    entries = []

    for doc in docs:
        entry_data = doc.to_dict()

        activity_ref = db.collection("activities").document(entry_data["activity_id"])
        activity_doc = activity_ref.get()
        activity_name = activity_doc.to_dict().get("name") if activity_doc.exists else "Unknown"

        time_entry = TimeEntry(
            id=entry_data["id"],
            activity_id=entry_data["activity_id"],
            activity_name=activity_name,
            start_datetime=entry_data["start_datetime"],
            end_datetime=entry_data.get("end_datetime"),
            duration_minutes=entry_data.get("duration_minutes"),
            notes=entry_data.get("notes"),
            tags=entry_data.get("tags", []),
            is_running=entry_data.get("is_running", False),
            created_at=entry_data["created_at"],
        )
        
        entries.append(time_entry)

    return entries