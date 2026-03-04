import json
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field


load_dotenv()


# Base directory where this file lives (works on Render and locally)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# JSON data files (stored alongside main.py, regardless of CWD)
EMPLOYEE_FILE = "employee.json"
HOLIDAYS_FILE = "holidays.json"
CLOCKING_FILE = "clocking.json"


def _data_path(filename: str) -> str:
    """Build an absolute path to a data file next to this module."""
    return os.path.join(BASE_DIR, filename)


def _load_json_file(filename: str) -> List[Dict[str, Any]]:
    path = _data_path(filename)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()
        if not content:
            return []
        data = json.loads(content)
        if not isinstance(data, list):
            raise ValueError(f"{path} must contain a JSON array")
        return data


def _save_json_file(filename: str, data: List[Dict[str, Any]]) -> None:
    path = _data_path(filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _iso(d: date) -> str:
    return d.isoformat()


def _paginate(items: List[Dict[str, Any]], page: int, page_size: int) -> Dict[str, Any]:
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "items": items[start:end],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _ensure_files_exist() -> None:
    for filename in (EMPLOYEE_FILE, HOLIDAYS_FILE, CLOCKING_FILE):
        path = _data_path(filename)
        if not os.path.exists(path):
            _save_json_file(filename, [])


class HolidayCreate(BaseModel):
    SUBTY: str = Field(default="0100")
    BEGDA: date
    ENDDA: date
    ABWTG: Optional[float] = None


class ClockEventCreate(BaseModel):
    DATE: Optional[date] = None


app = FastAPI(title="DHR API (JSON-backed)", version="1.0.0")


@app.on_event("startup")
def _startup() -> None:
    _ensure_files_exist()


@app.get("/employees")
async def get_all_employees(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> Dict[str, Any]:
    employees = _load_json_file(EMPLOYEE_FILE)
    return _paginate(employees, page, page_size)


@app.get("/employees/{pernr}/holidays")
async def get_employee_holidays(
    pernr: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> Dict[str, Any]:
    holidays = _load_json_file(HOLIDAYS_FILE)
    filtered = [h for h in holidays if str(h.get("PERNR")) == pernr]
    filtered.sort(key=lambda h: h.get("BEGDA", ""))
    return _paginate(filtered, page, page_size)


@app.get("/employees/{pernr}/clockings")
async def get_employee_clockings(
    pernr: str,
    start_date: Optional[date] = Query(None, description="Filter inclusive, YYYY-MM-DD"),
    end_date: Optional[date] = Query(None, description="Filter inclusive, YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> Dict[str, Any]:
    clockings = _load_json_file(CLOCKING_FILE)
    filtered: List[Dict[str, Any]] = []

    for entry in clockings:
        if str(entry.get("PERNR")) != pernr:
            continue

        entry_date_str = entry.get("DATE")
        if not entry_date_str:
            continue

        try:
            entry_date = _parse_date(entry_date_str)
        except ValueError:
            continue

        if start_date and entry_date < start_date:
            continue
        if end_date and entry_date > end_date:
            continue

        filtered.append(entry)

    filtered.sort(key=lambda e: e.get("DATE", ""))
    return _paginate(filtered, page, page_size)


@app.post("/employees/{pernr}/holidays")
async def add_holiday_request(pernr: str, payload: HolidayCreate) -> Dict[str, Any]:
    if payload.ENDDA < payload.BEGDA:
        raise HTTPException(status_code=400, detail="ENDDA must be on/after BEGDA")

    holidays = _load_json_file(HOLIDAYS_FILE)
    new_entry: Dict[str, Any] = {
        "PERNR": pernr,
        "SUBTY": payload.SUBTY,
        "BEGDA": _iso(payload.BEGDA),
        "ENDDA": _iso(payload.ENDDA),
    }
    if payload.ABWTG is not None:
        new_entry["ABWTG"] = payload.ABWTG

    holidays.append(new_entry)
    _save_json_file(HOLIDAYS_FILE, holidays)
    return new_entry


def _append_clock_event(pernr: str, status: str, event_date: date) -> Dict[str, Any]:
    clockings = _load_json_file(CLOCKING_FILE)
    new_entry: Dict[str, Any] = {
        "PERNR": pernr,
        "DATE": _iso(event_date),
        "STATUS": status,
    }
    clockings.append(new_entry)
    _save_json_file(CLOCKING_FILE, clockings)
    return new_entry


@app.post("/employees/{pernr}/clock-in")
async def add_clock_in(pernr: str, payload: ClockEventCreate) -> Dict[str, Any]:
    event_date = payload.DATE or date.today()
    return _append_clock_event(pernr, "CLOCKED_IN", event_date)


@app.post("/employees/{pernr}/clock-out")
async def add_clock_out(pernr: str, payload: ClockEventCreate) -> Dict[str, Any]:
    event_date = payload.DATE or date.today()
    return _append_clock_event(pernr, "CLOCKED_OUT", event_date)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

