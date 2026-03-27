from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
import re
import sqlite3
from urllib.parse import urlparse

from .errors import AppError

JST = timezone(timedelta(hours=9))
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SLASH_OR_FLEX_DATE_PATTERN = re.compile(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$")


def now_jst_iso() -> str:
    return datetime.now(JST).replace(microsecond=0).isoformat()


def today_jst() -> str:
    return datetime.now(JST).date().isoformat()


def normalize_optional_date(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    if stripped == "":
        return None
    if DATE_PATTERN.match(stripped):
        return stripped
    match = SLASH_OR_FLEX_DATE_PATTERN.match(stripped)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        try:
            return date(year, month, day).isoformat()
        except ValueError as exc:
            raise AppError(
                code="INVALID_DATE",
                message=f"{field_name} must be YYYY-MM-DD",
                status_code=422,
            ) from exc
    try:
        parsed = datetime.fromisoformat(stripped)
        return parsed.date().isoformat()
    except ValueError:
        pass
    try:
        parsed = date.fromisoformat(stripped)
        return parsed.isoformat()
    except ValueError as exc:
        raise AppError(
            code="INVALID_DATE",
            message=f"{field_name} must be YYYY-MM-DD",
            status_code=422,
        ) from exc


def require_positive_int(value: int, field_name: str) -> int:
    if int(value) <= 0:
        raise AppError(
            code="INVALID_QUANTITY",
            message=f"{field_name} must be > 0",
            status_code=422,
        )
    return int(value)


def require_non_empty(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise AppError(
            code="INVALID_FIELD",
            message=f"{field_name} must not be empty",
            status_code=422,
        )
    return normalized


def normalize_external_document_url(
    value: str | None,
    field_name: str,
    *,
    required: bool = False,
) -> str | None:
    if value is None:
        if required:
            raise AppError(
                code="INVALID_FIELD",
                message=f"{field_name} must not be empty",
                status_code=422,
            )
        return None
    normalized = str(value).strip()
    if not normalized:
        if required:
            raise AppError(
                code="INVALID_FIELD",
                message=f"{field_name} must not be empty",
                status_code=422,
            )
        return None
    parsed = urlparse(normalized)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise AppError(
            code="INVALID_DOCUMENT_URL",
            message=f"{field_name} must be a valid https URL",
            status_code=422,
        )
    return normalized


def to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}
