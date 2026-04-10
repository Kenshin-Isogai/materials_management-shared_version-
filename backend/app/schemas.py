from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, model_validator


class ItemCreate(BaseModel):
    item_number: str = Field(min_length=1)
    manufacturer_id: int | None = None
    manufacturer_name: str | None = None
    category: str | None = None
    url: str | None = None
    description: str | None = None


class ItemUpdate(BaseModel):
    item_number: str | None = None
    manufacturer_id: int | None = None
    manufacturer_name: str | None = None
    category: str | None = None
    url: str | None = None
    description: str | None = None


class ItemMetadataUpdateRow(BaseModel):
    item_id: int
    category: str | None = None
    url: str | None = None
    description: str | None = None

    @model_validator(mode="after")
    def validate_metadata_payload(self) -> "ItemMetadataUpdateRow":
        changed_fields = {"category", "url", "description"} & set(self.__pydantic_fields_set__)
        if not changed_fields:
            raise ValueError("at least one metadata field is required")
        return self


class ItemMetadataBulkUpdateRequest(BaseModel):
    rows: list[ItemMetadataUpdateRow] = Field(default_factory=list)
    continue_on_error: bool = True


class InventoryMoveRequest(BaseModel):
    item_id: int
    quantity: int = Field(gt=0)
    from_location: str = Field(min_length=1)
    to_location: str = Field(min_length=1)
    note: str | None = None
    batch_id: str | None = None


class InventoryConsumeRequest(BaseModel):
    item_id: int
    quantity: int = Field(gt=0)
    from_location: str = Field(min_length=1)
    note: str | None = None
    batch_id: str | None = None


class InventoryAdjustRequest(BaseModel):
    item_id: int
    quantity_delta: int
    location: str = Field(min_length=1)
    note: str | None = None
    batch_id: str | None = None


class InventoryBatchOperation(BaseModel):
    operation_type: Literal["MOVE", "CONSUME", "RESERVE", "ADJUST", "ARRIVAL"]
    item_id: int
    quantity: int = Field(gt=0)
    from_location: str | None = None
    to_location: str | None = None
    location: str | None = None
    note: str | None = None


class InventoryBatchRequest(BaseModel):
    operations: list[InventoryBatchOperation]
    batch_id: str | None = None




class InventoryImportRequest(BaseModel):
    batch_id: str | None = None


class ReservationImportRequest(BaseModel):
    pass


class OrderUpdateRequest(BaseModel):
    expected_arrival: str | None = None
    status: Literal["Ordered"] | None = None
    split_quantity: int | None = None
    project_id: int | None = None
    purchase_order_document_url: str | None = None


class OrderMergeRequest(BaseModel):
    source_purchase_order_line_id: int
    target_purchase_order_line_id: int
    expected_arrival: str | None = None


class QuotationUpdateRequest(BaseModel):
    issue_date: str | None = None
    quotation_document_url: str | None = None


class PurchaseOrderUpdateRequest(BaseModel):
    purchase_order_number: str | None = None
    purchase_order_document_url: str | None = None
    import_locked: bool | None = None


class ArrivalRequest(BaseModel):
    quantity: int | None = Field(default=None, gt=0)
    location: str | None = None


class PartialArrivalRequest(BaseModel):
    quantity: int = Field(gt=0)
    location: str | None = None


class ReservationCreate(BaseModel):
    item_id: int
    quantity: int = Field(gt=0)
    purpose: str | None = None
    deadline: str | None = None
    note: str | None = None
    project_id: int | None = None
    preferred_order_id: int | None = None


class ReservationUpdate(BaseModel):
    purpose: str | None = None
    deadline: str | None = None
    note: str | None = None


class ReservationBatchRequest(BaseModel):
    reservations: list[ReservationCreate]


class ReservationActionRequest(BaseModel):
    quantity: int | None = Field(default=None, gt=0)
    note: str | None = None


class ProjectRequirementInput(BaseModel):
    item_id: int | None = None
    assembly_id: int | None = None
    quantity: int = Field(gt=0)
    requirement_type: Literal["INITIAL", "SPARE", "REPLACEMENT"] = "INITIAL"
    note: str | None = None

    @model_validator(mode="after")
    def validate_target(self) -> "ProjectRequirementInput":
        has_item = self.item_id is not None
        has_assembly = self.assembly_id is not None
        if has_item == has_assembly:
            raise ValueError("exactly one of item_id or assembly_id is required")
        return self


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    status: Literal["PLANNING", "CONFIRMED", "ACTIVE", "COMPLETED", "CANCELLED"] = "PLANNING"
    planned_start: str | None = None
    requirements: list[ProjectRequirementInput] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: Literal["PLANNING", "CONFIRMED", "ACTIVE", "COMPLETED", "CANCELLED"] | None = None
    planned_start: str | None = None
    requirements: list[ProjectRequirementInput] | None = None


class ProjectRequirementPreviewRequest(BaseModel):
    text: str = ""


class ProjectRequirementPreviewExportRow(BaseModel):
    raw_target: str = ""
    status: Literal["exact", "high_confidence", "needs_review", "unresolved"]
    eligible_for_items_csv_export: bool | None = None


class ProjectRequirementUnresolvedItemsCsvRequest(BaseModel):
    text: str = ""
    rows: list[ProjectRequirementPreviewExportRow] = Field(default_factory=list)


class ConfirmAllocationRequest(BaseModel):
    target_date: str | None = None
    dry_run: bool = True
    expected_snapshot_signature: str | None = None


class BomLineInput(BaseModel):
    supplier: str
    item_number: str
    required_quantity: int = Field(ge=0)


class BomAnalyzeRequest(BaseModel):
    rows: list[BomLineInput]
    target_date: str | None = None


class BomReserveRequest(BaseModel):
    rows: list[BomLineInput]
    purpose: str | None = "BOM reserve"
    deadline: str | None = None
    note: str | None = None


class ProcurementBatchCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    note: str | None = None
    status: Literal["DRAFT", "SENT", "QUOTED", "ORDERED", "CLOSED", "CANCELLED"] = "DRAFT"


class ProcurementBatchUpdate(BaseModel):
    title: str | None = None
    status: Literal["DRAFT", "SENT", "QUOTED", "ORDERED", "CLOSED", "CANCELLED"] | None = None
    note: str | None = None

    @model_validator(mode="after")
    def validate_non_empty_payload(self) -> "ProcurementBatchUpdate":
        if not ({"title", "status", "note"} & set(self.__pydantic_fields_set__)):
            raise ValueError("at least one procurement batch field is required")
        return self


class ProcurementLineCreate(BaseModel):
    item_id: int
    source_type: Literal["PROJECT", "BOM", "ADHOC"] = "ADHOC"
    source_project_id: int | None = None
    requested_quantity: int = Field(gt=0)
    finalized_quantity: int | None = Field(default=None, gt=0)
    supplier_name: str | None = None
    expected_arrival: str | None = None
    linked_purchase_order_line_id: int | None = None
    linked_quotation_id: int | None = None
    status: Literal["DRAFT", "SENT", "QUOTED", "ORDERED", "CANCELLED"] = "DRAFT"
    note: str | None = None


class ProcurementBatchAddLinesRequest(BaseModel):
    lines: list[ProcurementLineCreate] = Field(default_factory=list)


class ProcurementLineUpdate(BaseModel):
    requested_quantity: int | None = Field(default=None, gt=0)
    finalized_quantity: int | None = Field(default=None, gt=0)
    supplier_name: str | None = None
    expected_arrival: str | None = None
    linked_purchase_order_line_id: int | None = None
    linked_quotation_id: int | None = None
    status: Literal["DRAFT", "SENT", "QUOTED", "ORDERED", "CANCELLED"] | None = None
    note: str | None = None

    @model_validator(mode="after")
    def validate_non_empty_payload(self) -> "ProcurementLineUpdate":
        if not (
            {
                "requested_quantity",
                "finalized_quantity",
                "supplier_name",
                "expected_arrival",
                "linked_purchase_order_line_id",
                "linked_quotation_id",
                "status",
                "note",
            }
            & set(self.__pydantic_fields_set__)
        ):
            raise ValueError("at least one procurement line field is required")
        return self


class ShortageInboxLine(BaseModel):
    item_id: int
    requested_quantity: int = Field(gt=0)
    source_type: Literal["PROJECT", "BOM", "ADHOC"]
    source_project_id: int | None = None
    supplier_name: str | None = None
    expected_arrival: str | None = None
    note: str | None = None


class ShortageInboxToProcurementRequest(BaseModel):
    batch_id: int | None = None
    create_batch_title: str | None = None
    create_batch_note: str | None = None
    confirm_project_id: int | None = None
    confirm_target_date: str | None = None
    lines: list[ShortageInboxLine] = Field(default_factory=list)


class ProcurementLinkConfirmation(BaseModel):
    purchase_order_line_id: int
    line_id: int
    confirmed: bool = True


class ConfirmProcurementLinksRequest(BaseModel):
    links: list[ProcurementLinkConfirmation] = Field(default_factory=list)


class TransactionUndoRequest(BaseModel):
    note: str | None = None


class ManufacturerCreate(BaseModel):
    name: str = Field(min_length=1)


class SupplierCreate(BaseModel):
    name: str = Field(min_length=1)


class AliasUpsertRequest(BaseModel):
    ordered_item_number: str = Field(min_length=1)
    canonical_item_id: int | None = None
    canonical_item_number: str | None = None
    units_per_order: int = Field(gt=0, default=1)


class AliasUpsertBySupplierNameRequest(BaseModel):
    supplier_name: str = Field(min_length=1)
    ordered_item_number: str = Field(min_length=1)
    canonical_item_id: int | None = None
    canonical_item_number: str | None = None
    units_per_order: int = Field(gt=0, default=1)


class CategoryMergeRequest(BaseModel):
    alias_category: str = Field(min_length=1)
    canonical_category: str = Field(min_length=1)


class PaginationQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=50, ge=1, le=500)


class ApiPayload(BaseModel):
    status: Literal["ok", "error"]
    data: Any | None = None
    pagination: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class UserCreate(BaseModel):
    username: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    email: str | None = None
    external_subject: str | None = None
    identity_provider: str | None = None
    hosted_domain: str | None = None
    role: str = "operator"
    is_active: bool = True

    @model_validator(mode="after")
    def validate_identity_fields(self) -> "UserCreate":
        if bool(self.external_subject) != bool(self.identity_provider):
            raise ValueError("identity_provider and external_subject must be set together")
        return self


class UserUpdate(BaseModel):
    username: str | None = None
    display_name: str | None = None
    email: str | None = None
    external_subject: str | None = None
    identity_provider: str | None = None
    hosted_domain: str | None = None
    role: str | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_non_empty_payload(self) -> "UserUpdate":
        if not (
            {
                "username",
                "display_name",
                "email",
                "external_subject",
                "identity_provider",
                "hosted_domain",
                "role",
                "is_active",
            }
            & set(self.__pydantic_fields_set__)
        ):
            raise ValueError("at least one user field is required")
        return self


class RegistrationRequestCreate(BaseModel):
    username: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    memo: str | None = None
    requested_role: str = "viewer"


class RegistrationRequestApprove(BaseModel):
    role: str | None = None
    username: str | None = None
    display_name: str | None = None


class RegistrationRequestReject(BaseModel):
    rejection_reason: str = Field(min_length=1)
