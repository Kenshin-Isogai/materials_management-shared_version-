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


class OrderUpdateRequest(BaseModel):
    expected_arrival: str | None = None
    status: Literal["Ordered"] | None = None


class UnregisteredBatchRequest(BaseModel):
    unregistered_root: str | None = None
    registered_root: str | None = None
    default_order_date: str | None = None
    continue_on_error: bool = False


class UnregisteredFileRetryRequest(BaseModel):
    csv_path: str = Field(min_length=1)
    unregistered_root: str | None = None
    registered_root: str | None = None
    default_order_date: str | None = None


class MissingItemRegistrationRow(BaseModel):
    item_number: str = Field(min_length=1)
    supplier: str = Field(min_length=1)
    manufacturer_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("manufacturer_name", "manufacturer"),
    )
    resolution_type: Literal["new_item", "alias"] = "new_item"
    category: str | None = None
    url: str | None = None
    description: str | None = None
    canonical_item_number: str | None = None
    units_per_order: int | None = None


class MissingItemRegistrationRequest(BaseModel):
    rows: list[MissingItemRegistrationRow] = Field(default_factory=list)


class ArrivalRequest(BaseModel):
    quantity: int | None = Field(default=None, gt=0)


class PartialArrivalRequest(BaseModel):
    quantity: int = Field(gt=0)


class ReservationCreate(BaseModel):
    item_id: int
    quantity: int = Field(gt=0)
    purpose: str | None = None
    deadline: str | None = None
    note: str | None = None
    project_id: int | None = None


class ReservationUpdate(BaseModel):
    purpose: str | None = None
    deadline: str | None = None
    note: str | None = None


class ReservationBatchRequest(BaseModel):
    reservations: list[ReservationCreate]


class ReservationActionRequest(BaseModel):
    quantity: int | None = Field(default=None, gt=0)
    note: str | None = None


class AssemblyComponentInput(BaseModel):
    item_id: int
    quantity: int = Field(gt=0)


class AssemblyCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    components: list[AssemblyComponentInput] = Field(default_factory=list)


class AssemblyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    components: list[AssemblyComponentInput] | None = None


class LocationAssemblyAssignment(BaseModel):
    assembly_id: int
    quantity: int = Field(gt=0)
    note: str | None = None


class LocationAssemblySetRequest(BaseModel):
    assignments: list[LocationAssemblyAssignment]


class ProjectRequirementInput(BaseModel):
    assembly_id: int | None = None
    item_id: int | None = None
    quantity: int = Field(gt=0)
    requirement_type: Literal["INITIAL", "SPARE", "REPLACEMENT"] = "INITIAL"
    note: str | None = None

    @model_validator(mode="after")
    def validate_one_target(self) -> "ProjectRequirementInput":
        if (self.assembly_id is None) == (self.item_id is None):
            raise ValueError("exactly one of assembly_id or item_id is required")
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


class BomLineInput(BaseModel):
    supplier: str
    item_number: str
    required_quantity: int = Field(ge=0)


class BomAnalyzeRequest(BaseModel):
    rows: list[BomLineInput]


class BomReserveRequest(BaseModel):
    rows: list[BomLineInput]
    purpose: str | None = "BOM reserve"
    deadline: str | None = None
    note: str | None = None


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
