from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import ORDERS_IMPORT_REGISTERED_ROOT, ORDERS_IMPORT_UNREGISTERED_ROOT
from .errors import AppError

CSV_FILES_DIR = "csv_files"
PDF_FILES_DIR = "pdf_files"
@dataclass(frozen=True)
class OrderImportRoots:
    unregistered_root: Path
    registered_root: Path
    unregistered_csv_root: Path
    unregistered_pdf_root: Path
    registered_csv_root: Path
    registered_pdf_root: Path


def build_roots(
    *,
    unregistered_root: str | Path | None = None,
    registered_root: str | Path | None = None,
) -> OrderImportRoots:
    unreg = Path(unregistered_root) if unregistered_root is not None else ORDERS_IMPORT_UNREGISTERED_ROOT
    reg = Path(registered_root) if registered_root is not None else ORDERS_IMPORT_REGISTERED_ROOT
    return OrderImportRoots(
        unregistered_root=unreg,
        registered_root=reg,
        unregistered_csv_root=unreg / CSV_FILES_DIR,
        unregistered_pdf_root=unreg / PDF_FILES_DIR,
        registered_csv_root=reg / CSV_FILES_DIR,
        registered_pdf_root=reg / PDF_FILES_DIR,
    )


def ensure_roots(roots: OrderImportRoots) -> None:
    for path in (
        roots.unregistered_root,
        roots.registered_root,
        roots.unregistered_csv_root,
        roots.unregistered_pdf_root,
        roots.registered_csv_root,
        roots.registered_pdf_root,
    ):
        path.mkdir(parents=True, exist_ok=True)


def supplier_from_unregistered_csv_path(
    csv_path: Path,
    *,
    roots: OrderImportRoots,
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
                "CSV must be placed under <unregistered>/csv_files/<supplier>/<file>.csv: "
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
    raise AppError(
        code="INVALID_UNREGISTERED_LAYOUT",
        message=f"CSV must be placed under csv_files/<supplier>/: {resolved_csv}",
        status_code=422,
    )




def registered_csv_supplier_dir(roots: OrderImportRoots, supplier_name: str) -> Path:
    return roots.registered_csv_root / supplier_name


def registered_pdf_supplier_dir(roots: OrderImportRoots, supplier_name: str) -> Path:
    return roots.registered_pdf_root / supplier_name


