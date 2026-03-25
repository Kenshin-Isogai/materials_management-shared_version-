from __future__ import annotations

from alembic import op


revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        """
        CREATE TABLE users (
            user_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'operator',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITHOUT TIME ZONE
        )
        """,
        "CREATE UNIQUE INDEX idx_users_username ON users (username)",
        "CREATE TABLE manufacturers (manufacturer_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, name TEXT NOT NULL UNIQUE CHECK (btrim(name) <> ''))",
        "CREATE TABLE suppliers (supplier_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, name TEXT NOT NULL UNIQUE CHECK (btrim(name) <> ''))",
        """
        CREATE TABLE items_master (
            item_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            item_number TEXT NOT NULL CHECK (btrim(item_number) <> ''),
            manufacturer_id INTEGER NOT NULL REFERENCES manufacturers (manufacturer_id),
            category TEXT,
            url TEXT,
            description TEXT,
            created_by INTEGER REFERENCES users (user_id),
            updated_by INTEGER REFERENCES users (user_id),
            UNIQUE (manufacturer_id, item_number)
        )
        """,
        """
        CREATE TABLE projects (
            project_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name TEXT NOT NULL UNIQUE CHECK (btrim(name) <> ''),
            description TEXT,
            status TEXT NOT NULL DEFAULT 'PLANNING' CHECK (status IN ('PLANNING', 'CONFIRMED', 'ACTIVE', 'COMPLETED', 'CANCELLED')),
            planned_start DATE,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITHOUT TIME ZONE,
            created_by INTEGER REFERENCES users (user_id),
            updated_by INTEGER REFERENCES users (user_id)
        )
        """,
        """
        CREATE TABLE inventory_ledger (
            ledger_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            item_id INTEGER NOT NULL REFERENCES items_master (item_id),
            location TEXT NOT NULL CHECK (btrim(location) <> ''),
            quantity INTEGER NOT NULL CHECK (quantity >= 0),
            last_updated TIMESTAMP WITHOUT TIME ZONE,
            updated_by INTEGER REFERENCES users (user_id),
            UNIQUE (item_id, location)
        )
        """,
        """
        CREATE TABLE quotations (
            quotation_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            supplier_id INTEGER NOT NULL REFERENCES suppliers (supplier_id),
            quotation_number TEXT NOT NULL CHECK (btrim(quotation_number) <> ''),
            issue_date DATE,
            pdf_link TEXT,
            created_by INTEGER REFERENCES users (user_id),
            updated_by INTEGER REFERENCES users (user_id),
            UNIQUE (supplier_id, quotation_number)
        )
        """,
        """
        CREATE TABLE orders (
            order_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            item_id INTEGER NOT NULL REFERENCES items_master (item_id),
            quotation_id INTEGER NOT NULL REFERENCES quotations (quotation_id),
            project_id INTEGER REFERENCES projects (project_id),
            project_id_manual INTEGER NOT NULL DEFAULT 0,
            order_amount INTEGER NOT NULL CHECK (order_amount > 0),
            ordered_quantity INTEGER CHECK (ordered_quantity IS NULL OR ordered_quantity > 0),
            ordered_item_number TEXT,
            order_date DATE NOT NULL,
            expected_arrival DATE,
            arrival_date DATE,
            status TEXT NOT NULL DEFAULT 'Ordered' CHECK (status IN ('Ordered', 'Arrived')),
            created_by INTEGER REFERENCES users (user_id),
            updated_by INTEGER REFERENCES users (user_id)
        )
        """,
        """
        CREATE TABLE order_lineage_events (
            event_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            event_type TEXT NOT NULL CHECK (event_type IN ('ETA_UPDATE', 'ETA_SPLIT', 'ETA_MERGE', 'ARRIVAL_SPLIT')),
            source_order_id INTEGER NOT NULL,
            target_order_id INTEGER,
            quantity INTEGER,
            previous_expected_arrival DATE,
            new_expected_arrival DATE,
            note TEXT,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
        )
        """,
        """
        CREATE TABLE transaction_log (
            log_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            timestamp TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            operation_type TEXT NOT NULL,
            item_id INTEGER NOT NULL REFERENCES items_master (item_id),
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            from_location TEXT,
            to_location TEXT,
            note TEXT,
            is_undone INTEGER NOT NULL DEFAULT 0 CHECK (is_undone IN (0, 1)),
            undo_of_log_id INTEGER REFERENCES transaction_log (log_id),
            batch_id TEXT,
            performed_by INTEGER REFERENCES users (user_id)
        )
        """,
        """
        CREATE TABLE reservations (
            reservation_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            item_id INTEGER NOT NULL REFERENCES items_master (item_id),
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            purpose TEXT,
            deadline DATE,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'RELEASED', 'CONSUMED')),
            released_at TIMESTAMP WITHOUT TIME ZONE,
            note TEXT,
            project_id INTEGER REFERENCES projects (project_id),
            created_by INTEGER REFERENCES users (user_id),
            updated_by INTEGER REFERENCES users (user_id)
        )
        """,
        """
        CREATE TABLE reservation_allocations (
            allocation_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            reservation_id INTEGER NOT NULL REFERENCES reservations (reservation_id) ON DELETE CASCADE,
            item_id INTEGER NOT NULL REFERENCES items_master (item_id),
            location TEXT NOT NULL CHECK (btrim(location) <> ''),
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'RELEASED', 'CONSUMED')),
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            released_at TIMESTAMP WITHOUT TIME ZONE,
            note TEXT
        )
        """,
        "CREATE TABLE assemblies (assembly_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, name TEXT NOT NULL UNIQUE CHECK (btrim(name) <> ''), description TEXT, created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL)",
        "CREATE TABLE assembly_components (assembly_id INTEGER NOT NULL REFERENCES assemblies (assembly_id) ON DELETE CASCADE, item_id INTEGER NOT NULL REFERENCES items_master (item_id) ON DELETE RESTRICT, quantity INTEGER NOT NULL CHECK (quantity > 0), PRIMARY KEY (assembly_id, item_id))",
        """
        CREATE TABLE location_assembly_usage (
            usage_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            location TEXT NOT NULL CHECK (btrim(location) <> ''),
            assembly_id INTEGER NOT NULL REFERENCES assemblies (assembly_id) ON DELETE CASCADE,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            note TEXT,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            UNIQUE (location, assembly_id)
        )
        """,
        """
        CREATE TABLE project_requirements (
            requirement_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects (project_id) ON DELETE CASCADE,
            assembly_id INTEGER REFERENCES assemblies (assembly_id),
            item_id INTEGER REFERENCES items_master (item_id),
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            requirement_type TEXT NOT NULL DEFAULT 'INITIAL' CHECK (requirement_type IN ('INITIAL', 'SPARE', 'REPLACEMENT')),
            note TEXT,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            CHECK ((assembly_id IS NOT NULL AND item_id IS NULL) OR (assembly_id IS NULL AND item_id IS NOT NULL))
        )
        """,
        """
        CREATE TABLE procurement_batches (
            batch_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            title TEXT NOT NULL CHECK (btrim(title) <> ''),
            status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'SENT', 'QUOTED', 'ORDERED', 'CLOSED', 'CANCELLED')),
            note TEXT,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            created_by INTEGER REFERENCES users (user_id),
            updated_by INTEGER REFERENCES users (user_id)
        )
        """,
        """
        CREATE TABLE procurement_lines (
            line_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            batch_id INTEGER NOT NULL REFERENCES procurement_batches (batch_id) ON DELETE CASCADE,
            item_id INTEGER NOT NULL REFERENCES items_master (item_id),
            source_type TEXT NOT NULL CHECK (source_type IN ('PROJECT', 'BOM', 'ADHOC')),
            source_project_id INTEGER REFERENCES projects (project_id) ON DELETE SET NULL,
            requested_quantity INTEGER NOT NULL CHECK (requested_quantity > 0),
            finalized_quantity INTEGER NOT NULL CHECK (finalized_quantity > 0),
            supplier_name TEXT,
            expected_arrival DATE,
            linked_order_id INTEGER REFERENCES orders (order_id) ON DELETE SET NULL,
            linked_quotation_id INTEGER REFERENCES quotations (quotation_id) ON DELETE SET NULL,
            status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'SENT', 'QUOTED', 'ORDERED', 'CANCELLED')),
            note TEXT,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            created_by INTEGER REFERENCES users (user_id),
            updated_by INTEGER REFERENCES users (user_id)
        )
        """,
        """
        CREATE TABLE rfq_batches (
            rfq_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects (project_id) ON DELETE CASCADE,
            title TEXT NOT NULL CHECK (btrim(title) <> ''),
            target_date DATE,
            status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED', 'CANCELLED')),
            note TEXT,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
        )
        """,
        """
        CREATE TABLE rfq_lines (
            line_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            rfq_id INTEGER NOT NULL REFERENCES rfq_batches (rfq_id) ON DELETE CASCADE,
            item_id INTEGER NOT NULL REFERENCES items_master (item_id),
            requested_quantity INTEGER NOT NULL CHECK (requested_quantity > 0),
            finalized_quantity INTEGER NOT NULL CHECK (finalized_quantity > 0),
            supplier_name TEXT,
            lead_time_days INTEGER CHECK (lead_time_days IS NULL OR lead_time_days >= 0),
            expected_arrival DATE,
            linked_order_id INTEGER REFERENCES orders (order_id) ON DELETE SET NULL,
            status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'SENT', 'QUOTED', 'ORDERED', 'CANCELLED')),
            note TEXT,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
        )
        """,
        """
        CREATE TABLE purchase_candidates (
            candidate_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            source_type TEXT NOT NULL CHECK (source_type IN ('BOM', 'PROJECT')),
            project_id INTEGER REFERENCES projects (project_id) ON DELETE SET NULL,
            item_id INTEGER REFERENCES items_master (item_id),
            supplier_name TEXT,
            ordered_item_number TEXT,
            canonical_item_number TEXT,
            required_quantity INTEGER NOT NULL CHECK (required_quantity >= 0),
            available_stock INTEGER NOT NULL CHECK (available_stock >= 0),
            shortage_quantity INTEGER NOT NULL CHECK (shortage_quantity >= 0),
            target_date DATE,
            status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'ORDERING', 'ORDERED', 'CANCELLED')),
            note TEXT,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
        )
        """,
        """
        CREATE TABLE supplier_item_aliases (
            alias_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            supplier_id INTEGER NOT NULL REFERENCES suppliers (supplier_id),
            ordered_item_number TEXT NOT NULL CHECK (btrim(ordered_item_number) <> ''),
            canonical_item_id INTEGER NOT NULL REFERENCES items_master (item_id),
            units_per_order INTEGER NOT NULL CHECK (units_per_order > 0),
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            UNIQUE (supplier_id, ordered_item_number)
        )
        """,
        """
        CREATE TABLE category_aliases (
            alias_category TEXT PRIMARY KEY NOT NULL CHECK (btrim(alias_category) <> ''),
            canonical_category TEXT NOT NULL CHECK (btrim(canonical_category) <> ''),
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            CHECK (alias_category <> canonical_category)
        )
        """,
        """
        CREATE TABLE import_jobs (
            import_job_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            import_type TEXT NOT NULL CHECK (import_type IN ('items')),
            source_name TEXT NOT NULL,
            source_content TEXT NOT NULL,
            continue_on_error INTEGER NOT NULL CHECK (continue_on_error IN (0, 1)),
            status TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'partial', 'error')),
            processed INTEGER NOT NULL DEFAULT 0,
            created_count INTEGER NOT NULL DEFAULT 0,
            duplicate_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            lifecycle_state TEXT NOT NULL DEFAULT 'active' CHECK (lifecycle_state IN ('active', 'undone')),
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            undone_at TIMESTAMP WITHOUT TIME ZONE,
            redo_of_job_id INTEGER REFERENCES import_jobs (import_job_id),
            last_redo_job_id INTEGER REFERENCES import_jobs (import_job_id),
            created_by INTEGER REFERENCES users (user_id)
        )
        """,
        """
        CREATE TABLE import_job_effects (
            effect_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            import_job_id INTEGER NOT NULL REFERENCES import_jobs (import_job_id) ON DELETE CASCADE,
            row_number INTEGER NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('created', 'duplicate', 'error')),
            entry_type TEXT CHECK (entry_type IS NULL OR entry_type IN ('item', 'alias')),
            effect_type TEXT NOT NULL,
            item_id INTEGER,
            alias_id INTEGER,
            supplier_id INTEGER,
            item_number TEXT,
            supplier_name TEXT,
            canonical_item_number TEXT,
            units_per_order INTEGER,
            message TEXT,
            code TEXT,
            before_state TEXT,
            after_state TEXT,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
        )
        """,
    ]
    for statement in statements:
        op.execute(statement)

    index_statements = [
        "CREATE INDEX idx_transaction_log_batch_id ON transaction_log (batch_id)",
        "CREATE INDEX idx_transaction_log_undo_of_log_id ON transaction_log (undo_of_log_id)",
        "CREATE INDEX idx_reservations_item_id ON reservations (item_id)",
        "CREATE INDEX idx_reservations_status ON reservations (status)",
        "CREATE INDEX idx_reservations_deadline ON reservations (deadline)",
        "CREATE INDEX idx_reservations_project_id ON reservations (project_id)",
        "CREATE INDEX idx_reservation_allocations_reservation_id ON reservation_allocations (reservation_id)",
        "CREATE INDEX idx_reservation_allocations_item_loc_status ON reservation_allocations (item_id, location, status)",
        "CREATE INDEX idx_assembly_components_item_id ON assembly_components (item_id)",
        "CREATE INDEX idx_location_assembly_usage_location ON location_assembly_usage (location)",
        "CREATE INDEX idx_location_assembly_usage_assembly_id ON location_assembly_usage (assembly_id)",
        "CREATE INDEX idx_projects_status ON projects (status)",
        "CREATE INDEX idx_projects_planned_start ON projects (planned_start)",
        "CREATE INDEX idx_project_requirements_project_id ON project_requirements (project_id)",
        "CREATE INDEX idx_project_requirements_assembly_id ON project_requirements (assembly_id)",
        "CREATE INDEX idx_project_requirements_item_id ON project_requirements (item_id)",
        "CREATE INDEX idx_procurement_batches_status_updated ON procurement_batches (status, updated_at)",
        "CREATE INDEX idx_procurement_lines_batch_id ON procurement_lines (batch_id)",
        "CREATE INDEX idx_procurement_lines_item_status_expected_arrival ON procurement_lines (item_id, status, expected_arrival)",
        "CREATE INDEX idx_procurement_lines_source_project_id ON procurement_lines (source_project_id)",
        "CREATE INDEX idx_procurement_lines_linked_order_id ON procurement_lines (linked_order_id)",
        "CREATE INDEX idx_rfq_batches_project_id_status ON rfq_batches (project_id, status, target_date)",
        "CREATE INDEX idx_rfq_lines_rfq_id ON rfq_lines (rfq_id)",
        "CREATE INDEX idx_rfq_lines_item_id_status ON rfq_lines (item_id, status, expected_arrival)",
        "CREATE INDEX idx_rfq_lines_linked_order_id ON rfq_lines (linked_order_id)",
        "CREATE INDEX idx_purchase_candidates_status_target_date ON purchase_candidates (status, target_date)",
        "CREATE INDEX idx_purchase_candidates_source_type ON purchase_candidates (source_type)",
        "CREATE INDEX idx_purchase_candidates_project_id ON purchase_candidates (project_id)",
        "CREATE INDEX idx_purchase_candidates_item_id ON purchase_candidates (item_id)",
        "CREATE INDEX idx_orders_project_id ON orders (project_id)",
        "CREATE INDEX idx_orders_ordered_item_number ON orders (ordered_item_number)",
        "CREATE INDEX idx_orders_status_expected_arrival ON orders (status, expected_arrival)",
        "CREATE INDEX idx_orders_item_status_expected_arrival ON orders (item_id, status, expected_arrival)",
        "CREATE INDEX idx_order_lineage_events_source ON order_lineage_events (source_order_id, created_at)",
        "CREATE INDEX idx_order_lineage_events_target ON order_lineage_events (target_order_id, created_at)",
        "CREATE INDEX idx_order_lineage_events_type_created ON order_lineage_events (event_type, created_at)",
        "CREATE INDEX idx_supplier_item_aliases_canonical_item_id ON supplier_item_aliases (canonical_item_id)",
        "CREATE INDEX idx_category_aliases_canonical_category ON category_aliases (canonical_category)",
        "CREATE INDEX idx_category_aliases_updated_at ON category_aliases (updated_at)",
        "CREATE INDEX idx_import_jobs_type_created_at ON import_jobs (import_type, created_at)",
        "CREATE INDEX idx_import_jobs_redo_of_job_id ON import_jobs (redo_of_job_id)",
        "CREATE INDEX idx_import_job_effects_job_row ON import_job_effects (import_job_id, row_number, effect_id)",
    ]
    for statement in index_statements:
        op.execute(statement)

    trigger_statements = [
        """
        CREATE OR REPLACE FUNCTION app_current_user_id() RETURNS INTEGER LANGUAGE plpgsql AS $$
        DECLARE raw_value TEXT;
        BEGIN
            raw_value := current_setting('app.user_id', true);
            IF raw_value IS NULL OR btrim(raw_value) = '' THEN RETURN NULL; END IF;
            RETURN raw_value::INTEGER;
        EXCEPTION WHEN OTHERS THEN
            RETURN NULL;
        END;
        $$;
        """,
        """
        CREATE OR REPLACE FUNCTION set_created_updated_by() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE actor_id INTEGER;
        BEGIN
            actor_id := app_current_user_id();
            IF TG_OP = 'INSERT' THEN
                IF NEW.created_by IS NULL THEN NEW.created_by := actor_id; END IF;
                IF NEW.updated_by IS NULL THEN NEW.updated_by := actor_id; END IF;
            ELSE
                NEW.updated_by := actor_id;
            END IF;
            RETURN NEW;
        END;
        $$;
        """,
        """
        CREATE OR REPLACE FUNCTION set_transaction_performed_by() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.performed_by IS NULL THEN NEW.performed_by := app_current_user_id(); END IF;
            RETURN NEW;
        END;
        $$;
        """,
        """
        CREATE OR REPLACE FUNCTION set_inventory_updated_by() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_by := app_current_user_id();
            RETURN NEW;
        END;
        $$;
        """,
        """
        CREATE OR REPLACE FUNCTION set_import_job_created_by() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.created_by IS NULL THEN NEW.created_by := app_current_user_id(); END IF;
            RETURN NEW;
        END;
        $$;
        """,
        """
        CREATE OR REPLACE FUNCTION normalize_order_fields() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.status IS NULL OR btrim(NEW.status) = '' THEN NEW.status := 'Ordered'; END IF;
            IF NEW.ordered_quantity IS NULL THEN NEW.ordered_quantity := NEW.order_amount; END IF;
            IF NEW.ordered_item_number IS NULL OR btrim(NEW.ordered_item_number) = '' THEN
                SELECT item_number INTO NEW.ordered_item_number FROM items_master WHERE item_id = NEW.item_id;
            END IF;
            RETURN NEW;
        END;
        $$;
        """,
        "CREATE TRIGGER trg_items_master_audit BEFORE INSERT OR UPDATE ON items_master FOR EACH ROW EXECUTE FUNCTION set_created_updated_by()",
        "CREATE TRIGGER trg_projects_audit BEFORE INSERT OR UPDATE ON projects FOR EACH ROW EXECUTE FUNCTION set_created_updated_by()",
        "CREATE TRIGGER trg_quotations_audit BEFORE INSERT OR UPDATE ON quotations FOR EACH ROW EXECUTE FUNCTION set_created_updated_by()",
        "CREATE TRIGGER trg_orders_audit BEFORE INSERT OR UPDATE ON orders FOR EACH ROW EXECUTE FUNCTION set_created_updated_by()",
        "CREATE TRIGGER trg_reservations_audit BEFORE INSERT OR UPDATE ON reservations FOR EACH ROW EXECUTE FUNCTION set_created_updated_by()",
        "CREATE TRIGGER trg_procurement_batches_audit BEFORE INSERT OR UPDATE ON procurement_batches FOR EACH ROW EXECUTE FUNCTION set_created_updated_by()",
        "CREATE TRIGGER trg_procurement_lines_audit BEFORE INSERT OR UPDATE ON procurement_lines FOR EACH ROW EXECUTE FUNCTION set_created_updated_by()",
        "CREATE TRIGGER trg_inventory_ledger_audit BEFORE INSERT OR UPDATE ON inventory_ledger FOR EACH ROW EXECUTE FUNCTION set_inventory_updated_by()",
        "CREATE TRIGGER trg_import_jobs_audit BEFORE INSERT ON import_jobs FOR EACH ROW EXECUTE FUNCTION set_import_job_created_by()",
        "CREATE TRIGGER trg_transaction_log_audit BEFORE INSERT ON transaction_log FOR EACH ROW EXECUTE FUNCTION set_transaction_performed_by()",
        "CREATE TRIGGER trg_orders_normalize BEFORE INSERT OR UPDATE ON orders FOR EACH ROW EXECUTE FUNCTION normalize_order_fields()",
    ]
    for statement in trigger_statements:
        op.execute(statement)


def downgrade() -> None:
    for statement in (
        "DROP TRIGGER IF EXISTS trg_orders_normalize ON orders",
        "DROP TRIGGER IF EXISTS trg_transaction_log_audit ON transaction_log",
        "DROP TRIGGER IF EXISTS trg_import_jobs_audit ON import_jobs",
        "DROP TRIGGER IF EXISTS trg_inventory_ledger_audit ON inventory_ledger",
        "DROP TRIGGER IF EXISTS trg_procurement_lines_audit ON procurement_lines",
        "DROP TRIGGER IF EXISTS trg_procurement_batches_audit ON procurement_batches",
        "DROP TRIGGER IF EXISTS trg_reservations_audit ON reservations",
        "DROP TRIGGER IF EXISTS trg_orders_audit ON orders",
        "DROP TRIGGER IF EXISTS trg_quotations_audit ON quotations",
        "DROP TRIGGER IF EXISTS trg_projects_audit ON projects",
        "DROP TRIGGER IF EXISTS trg_items_master_audit ON items_master",
        "DROP FUNCTION IF EXISTS normalize_order_fields()",
        "DROP FUNCTION IF EXISTS set_import_job_created_by()",
        "DROP FUNCTION IF EXISTS set_inventory_updated_by()",
        "DROP FUNCTION IF EXISTS set_transaction_performed_by()",
        "DROP FUNCTION IF EXISTS set_created_updated_by()",
        "DROP FUNCTION IF EXISTS app_current_user_id()",
        "DROP INDEX IF EXISTS idx_import_job_effects_job_row",
        "DROP INDEX IF EXISTS idx_import_jobs_redo_of_job_id",
        "DROP INDEX IF EXISTS idx_import_jobs_type_created_at",
        "DROP INDEX IF EXISTS idx_category_aliases_updated_at",
        "DROP INDEX IF EXISTS idx_category_aliases_canonical_category",
        "DROP INDEX IF EXISTS idx_supplier_item_aliases_canonical_item_id",
        "DROP INDEX IF EXISTS idx_order_lineage_events_type_created",
        "DROP INDEX IF EXISTS idx_order_lineage_events_target",
        "DROP INDEX IF EXISTS idx_order_lineage_events_source",
        "DROP INDEX IF EXISTS idx_orders_item_status_expected_arrival",
        "DROP INDEX IF EXISTS idx_orders_status_expected_arrival",
        "DROP INDEX IF EXISTS idx_orders_ordered_item_number",
        "DROP INDEX IF EXISTS idx_orders_project_id",
        "DROP INDEX IF EXISTS idx_purchase_candidates_item_id",
        "DROP INDEX IF EXISTS idx_purchase_candidates_project_id",
        "DROP INDEX IF EXISTS idx_purchase_candidates_source_type",
        "DROP INDEX IF EXISTS idx_purchase_candidates_status_target_date",
        "DROP INDEX IF EXISTS idx_rfq_lines_linked_order_id",
        "DROP INDEX IF EXISTS idx_rfq_lines_item_id_status",
        "DROP INDEX IF EXISTS idx_rfq_lines_rfq_id",
        "DROP INDEX IF EXISTS idx_rfq_batches_project_id_status",
        "DROP INDEX IF EXISTS idx_procurement_lines_linked_order_id",
        "DROP INDEX IF EXISTS idx_procurement_lines_source_project_id",
        "DROP INDEX IF EXISTS idx_procurement_lines_item_status_expected_arrival",
        "DROP INDEX IF EXISTS idx_procurement_lines_batch_id",
        "DROP INDEX IF EXISTS idx_procurement_batches_status_updated",
        "DROP INDEX IF EXISTS idx_project_requirements_item_id",
        "DROP INDEX IF EXISTS idx_project_requirements_assembly_id",
        "DROP INDEX IF EXISTS idx_project_requirements_project_id",
        "DROP INDEX IF EXISTS idx_projects_planned_start",
        "DROP INDEX IF EXISTS idx_projects_status",
        "DROP INDEX IF EXISTS idx_location_assembly_usage_assembly_id",
        "DROP INDEX IF EXISTS idx_location_assembly_usage_location",
        "DROP INDEX IF EXISTS idx_assembly_components_item_id",
        "DROP INDEX IF EXISTS idx_reservation_allocations_item_loc_status",
        "DROP INDEX IF EXISTS idx_reservation_allocations_reservation_id",
        "DROP INDEX IF EXISTS idx_reservations_project_id",
        "DROP INDEX IF EXISTS idx_reservations_deadline",
        "DROP INDEX IF EXISTS idx_reservations_status",
        "DROP INDEX IF EXISTS idx_reservations_item_id",
        "DROP INDEX IF EXISTS idx_transaction_log_undo_of_log_id",
        "DROP INDEX IF EXISTS idx_transaction_log_batch_id",
        "DROP INDEX IF EXISTS idx_users_username",
        "DROP TABLE IF EXISTS import_job_effects",
        "DROP TABLE IF EXISTS import_jobs",
        "DROP TABLE IF EXISTS category_aliases",
        "DROP TABLE IF EXISTS supplier_item_aliases",
        "DROP TABLE IF EXISTS purchase_candidates",
        "DROP TABLE IF EXISTS rfq_lines",
        "DROP TABLE IF EXISTS rfq_batches",
        "DROP TABLE IF EXISTS procurement_lines",
        "DROP TABLE IF EXISTS procurement_batches",
        "DROP TABLE IF EXISTS project_requirements",
        "DROP TABLE IF EXISTS location_assembly_usage",
        "DROP TABLE IF EXISTS assembly_components",
        "DROP TABLE IF EXISTS assemblies",
        "DROP TABLE IF EXISTS reservation_allocations",
        "DROP TABLE IF EXISTS reservations",
        "DROP TABLE IF EXISTS transaction_log",
        "DROP TABLE IF EXISTS order_lineage_events",
        "DROP TABLE IF EXISTS orders",
        "DROP TABLE IF EXISTS quotations",
        "DROP TABLE IF EXISTS inventory_ledger",
        "DROP TABLE IF EXISTS projects",
        "DROP TABLE IF EXISTS items_master",
        "DROP TABLE IF EXISTS suppliers",
        "DROP TABLE IF EXISTS manufacturers",
        "DROP TABLE IF EXISTS users",
    ):
        op.execute(statement)
