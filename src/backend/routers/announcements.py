"""Announcement endpoints for the High School Management System API."""

from datetime import date
import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..database import announcements_collection, teachers_collection

router = APIRouter(prefix="/announcements", tags=["announcements"])
logger = logging.getLogger(__name__)


class AnnouncementPayload(BaseModel):
    """Input payload for creating and updating announcements."""

    message: str = Field(min_length=1, max_length=300)
    expiration_date: str
    start_date: Optional[str] = None


def parse_iso_date(raw_value: str, field_name: str) -> date:
    """Parse a YYYY-MM-DD date string, raising a 400 error when invalid."""
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name}. Expected format: YYYY-MM-DD"
        ) from exc


def validate_date_window(start_date: Optional[str], expiration_date: str) -> Dict[str, Optional[str]]:
    """Validate and normalize start/expiration dates."""
    parsed_expiration = parse_iso_date(expiration_date, "expiration_date")
    parsed_start = parse_iso_date(start_date, "start_date") if start_date else None

    if parsed_start and parsed_start > parsed_expiration:
        raise HTTPException(
            status_code=400,
            detail="start_date cannot be after expiration_date"
        )

    return {
        "start_date": parsed_start.isoformat() if parsed_start else None,
        "expiration_date": parsed_expiration.isoformat()
    }


def require_signed_in_user(teacher_username: Optional[str]) -> Dict[str, Any]:
    """Ensure the provided username belongs to an existing teacher account."""
    if not teacher_username:
        raise HTTPException(status_code=401, detail="Authentication required")

    teacher = teachers_collection.find_one({"_id": teacher_username})
    if not teacher:
        raise HTTPException(status_code=401, detail="Invalid teacher credentials")

    return teacher


def serialize_announcement(item: Dict[str, Any]) -> Dict[str, Any]:
    """Map MongoDB document fields to API-friendly output."""
    return {
        "id": item["_id"],
        "message": item.get("message", ""),
        "start_date": item.get("start_date"),
        "expiration_date": item.get("expiration_date")
    }


@router.get("", response_model=List[Dict[str, Any]])
def get_active_announcements() -> List[Dict[str, Any]]:
    """Return currently active announcements for the public banner."""
    today = date.today().isoformat()

    query = {
        "expiration_date": {"$gte": today},
        "$or": [
            {"start_date": None},
            {"start_date": {"$exists": False}},
            {"start_date": {"$lte": today}}
        ]
    }

    announcements: List[Dict[str, Any]] = []
    for item in announcements_collection.find(query).sort("expiration_date", 1):
        announcements.append(serialize_announcement(item))

    return announcements


@router.get("/all", response_model=List[Dict[str, Any]])
def get_all_announcements(teacher_username: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """Return every announcement (active and expired) for authenticated users."""
    require_signed_in_user(teacher_username)

    announcements: List[Dict[str, Any]] = []
    for item in announcements_collection.find({}).sort("expiration_date", 1):
        announcements.append(serialize_announcement(item))

    return announcements


@router.post("", response_model=Dict[str, str])
def create_announcement(
    payload: AnnouncementPayload,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, str]:
    """Create a new announcement (requires authenticated user)."""
    require_signed_in_user(teacher_username)

    cleaned_message = payload.message.strip()
    if not cleaned_message:
        raise HTTPException(status_code=400, detail="message cannot be blank")

    normalized_dates = validate_date_window(payload.start_date, payload.expiration_date)
    announcement_id = f"announcement-{uuid4().hex[:10]}"

    try:
        announcements_collection.insert_one(
            {
                "_id": announcement_id,
                "message": cleaned_message,
                "start_date": normalized_dates["start_date"],
                "expiration_date": normalized_dates["expiration_date"]
            }
        )
    except Exception:
        logger.exception("Failed to create announcement")
        raise HTTPException(status_code=500, detail="Unable to save announcement")

    return {"message": "Announcement created"}


@router.put("/{announcement_id}", response_model=Dict[str, str])
def update_announcement(
    announcement_id: str,
    payload: AnnouncementPayload,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, str]:
    """Update an existing announcement (requires authenticated user)."""
    require_signed_in_user(teacher_username)

    cleaned_message = payload.message.strip()
    if not cleaned_message:
        raise HTTPException(status_code=400, detail="message cannot be blank")

    normalized_dates = validate_date_window(payload.start_date, payload.expiration_date)

    result = announcements_collection.update_one(
        {"_id": announcement_id},
        {
            "$set": {
                "message": cleaned_message,
                "start_date": normalized_dates["start_date"],
                "expiration_date": normalized_dates["expiration_date"]
            }
        }
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement updated"}


@router.delete("/{announcement_id}", response_model=Dict[str, str])
def delete_announcement(
    announcement_id: str,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, str]:
    """Delete an announcement (requires authenticated user)."""
    require_signed_in_user(teacher_username)

    result = announcements_collection.delete_one({"_id": announcement_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement deleted"}
