from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import (
    QUOTATIONS_REGISTERED_ROOT,
    QUOTATIONS_UNREGISTERED_ROOT,
    WORKSPACE_ROOT,
)
from .errors import AppError

CSV_FILES_DIR = "csv_files"
PDF_FILES_DIR = "pdf_files"
_CANONICAL_ROOT_CHILDREN = {CSV_FILES_DIR, PDF_FILES_DIR}

_TYPO_SEGMENT_MAP = {
    "quatations": "quotations",
    "unregistred": "unregistered",
    "registred": "registered",
}


@dataclass(frozen=True)
class QuotationRoots:
    unregistered_root: Path
    registered_root: Path
    unregistered_csv_root: Path
    unregistered_pdf_root: Path
    registered_csv_root: Path
    registered_pdf_root: Path
    unregistered_missing_root: Path


def build_roots(
    *,
    unregistered_root: str | Path | None = None,
    registered_root: str | Path | None = None,
) -> QuotationRoots:
    unreg = Path(unregistered_root) if unregistered_root is not None else QUOTATIONS_UNREGISTERED_ROOT
    reg = Path(registered_root) if registered_root is not None else QUOTATIONS_REGISTERED_ROOT
    return QuotationRoots(
        unregistered_root=unreg,
        registered_root=reg,
        unregistered_csv_root=unreg / CSV_FILES_DIR,
        unregistered_pdf_root=unreg / PDF_FILES_DIR,
        registered_csv_root=reg / CSV_FILES_DIR,
        registered_pdf_root=reg / PDF_FILES_DIR,
        unregistered_missing_root=unreg / "missing_item_registers",
    )


def ensure_roots(roots: QuotationRoots) -> None:
    for path in (
        roots.unregistered_root,
        roots.registered_root,
        roots.unregistered_csv_root,
        roots.unregistered_pdf_root,
        roots.unregistered_missing_root,
        roots.registered_csv_root,
        roots.registered_pdf_root,
    ):
        path.mkdir(parents=True, exist_ok=True)


def safe_workspace_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(WORKSPACE_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def normalize_legacy_path_text(raw: str) -> tuple[str, bool]:
    text = (raw or "").strip()
    if not text:
        return "", False
    normalized = text.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part and part != "."]
    remapped = [_TYPO_SEGMENT_MAP.get(part.lower(), part) for part in parts]
    fixed = "/".join(remapped)
    return fixed, fixed != text


def supplier_from_unregistered_csv_path(
    csv_path: Path,
    *,
    roots: QuotationRoots,
) -> tuple[str, list[str]]:
    resolved_csv = csv_path.resolve()
    resolved_unreg = roots.unregistered_root.resolve()
    try:
        relative = resolved_csv.relative_to(resolved_unreg)
    except ValueError as exc:
        raise AppError(
            code="INVALID_UNREGISTERED_PATH",
            message=f"{resolved_csv} is not under {resolved_unreg}",
            status_code=422,
        ) from exc

    if len(relative.parts) < 2:
        raise AppError(
            code="INVALID_UNREGISTERED_LAYOUT",
            message=(
                "CSV must be placed under "
                "<unregistered>/csv_files/<supplier>/<file>.csv or legacy "
                "<unregistered>/<supplier>/<file>.csv: "
                f"{resolved_csv}"
            ),
            status_code=422,
        )

    first = relative.parts[0]
    if first == CSV_FILES_DIR:
        if len(relative.parts) < 3:
            raise AppError(
                code="INVALID_UNREGISTERED_LAYOUT",
                message=f"CSV under csv_files must include supplier folder: {resolved_csv}",
                status_code=422,
            )
        return relative.parts[1], []
    if first == PDF_FILES_DIR:
        raise AppError(
            code="INVALID_UNREGISTERED_LAYOUT",
            message=f"CSV cannot be under pdf_files: {resolved_csv}",
            status_code=422,
        )
    return first, [
        "Legacy unregistered CSV layout detected. "
        "Please migrate to <unregistered>/csv_files/<supplier>/."
    ]


def validate_retry_unregistered_csv_path(csv_path: str | Path, *, roots: QuotationRoots) -> Path:
    path = Path(csv_path)
    if not path.exists():
        raise AppError(
            code="UNREGISTERED_CSV_NOT_FOUND",
            message=f"CSV not found: {path}",
            status_code=404,
        )
    resolved = path.resolve()
    unreg = roots.unregistered_root.resolve()
    try:
        resolved.relative_to(unreg)
    except ValueError as exc:
        raise AppError(
            code="INVALID_UNREGISTERED_PATH",
            message=f"{resolved} is not under {unreg}",
            status_code=422,
        ) from exc
    if resolved.suffix.lower() != ".csv":
        raise AppError(
            code="INVALID_CSV",
            message=f"File must be CSV: {resolved}",
            status_code=422,
        )
    if resolved.name.endswith("_missing_items_registration.csv"):
        raise AppError(
            code="INVALID_CSV",
            message=f"Retry target must be order CSV, not missing-items CSV: {resolved.name}",
            status_code=422,
        )
    return resolved


def iter_unregistered_missing_csvs(roots: QuotationRoots) -> list[Path]:
    paths = {
        *roots.unregistered_csv_root.rglob("*_missing_items_registration.csv"),
        *roots.unregistered_missing_root.rglob("*_missing_items_registration.csv"),
    }
    return sorted(paths)


def iter_unregistered_order_csvs(roots: QuotationRoots) -> list[Path]:
    return sorted(
        [
            p
            for p in roots.unregistered_csv_root.rglob("*.csv")
            if not p.name.endswith("_missing_items_registration.csv")
        ]
    )


def registered_csv_supplier_dir(roots: QuotationRoots, supplier_name: str) -> Path:
    return roots.registered_csv_root / supplier_name


def registered_pdf_supplier_dir(roots: QuotationRoots, supplier_name: str) -> Path:
    return roots.registered_pdf_root / supplier_name


def is_legacy_supplier_dir(path: Path) -> bool:
    return path.is_dir() and path.name not in _CANONICAL_ROOT_CHILDREN


def normalize_pdf_link(
    *,
    pdf_link: str,
    supplier_name: str,
    roots: QuotationRoots,
    csv_path: Path | None = None,
) -> tuple[Path | None, str, list[dict[str, str]], list[str]]:
    raw = (pdf_link or "").strip()
    if not raw:
        return None, "", [], []

    normalized, changed = normalize_legacy_path_text(raw)
    normalizations: list[dict[str, str]] = []
    if changed:
        normalizations.append(
            {
                "kind": "pdf_link_text",
                "from": raw,
                "to": normalized,
            }
        )

    warnings: list[str] = []
    preferred_text = normalized or raw
    search_texts = [raw]
    if preferred_text != raw:
        search_texts.append(preferred_text)

    candidates: list[Path] = []
    seen: set[str] = set()
    for text in search_texts:
        candidate = Path(text)
        candidate_key = str(candidate)
        if candidate_key in seen:
            continue
        seen.add(candidate_key)

        if candidate.is_absolute():
            candidates.append(candidate)
            continue

        if csv_path is not None:
            candidates.append(csv_path.parent / candidate)
            candidates.append(csv_path.parent / candidate.name)

        candidates.append(roots.unregistered_pdf_root / supplier_name / candidate)
        candidates.append(roots.unregistered_pdf_root / supplier_name / candidate.name)
        candidates.append(roots.unregistered_root / supplier_name / candidate)
        candidates.append(roots.unregistered_root / supplier_name / candidate.name)
        candidates.append(roots.registered_pdf_root / supplier_name / candidate)
        candidates.append(roots.registered_pdf_root / supplier_name / candidate.name)
        candidates.append(WORKSPACE_ROOT / candidate)

    dedup: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in dedup:
            continue
        dedup.add(key)
        if candidate.exists() and candidate.is_file():
            return candidate.resolve(), preferred_text, normalizations, warnings

    warnings.append(f"Unable to resolve pdf_link '{raw}' for supplier '{supplier_name}'.")
    return None, preferred_text, normalizations, warnings
