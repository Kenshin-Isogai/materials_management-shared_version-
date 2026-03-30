from alembic import op


revision = "010_purchase_orders_header"
down_revision = "009_oidc_user_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    statements = [
        """
        CREATE TABLE purchase_orders (
            purchase_order_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            supplier_id INTEGER NOT NULL REFERENCES suppliers (supplier_id),
            purchase_order_document_url TEXT,
            created_by INTEGER REFERENCES users (user_id),
            updated_by INTEGER REFERENCES users (user_id),
            UNIQUE (supplier_id, purchase_order_document_url)
        )
        """,
        "ALTER TABLE orders ADD COLUMN purchase_order_id INTEGER",
        """
        INSERT INTO purchase_orders (supplier_id, purchase_order_document_url)
        SELECT DISTINCT q.supplier_id, o.purchase_order_document_url
        FROM orders o
        JOIN quotations q ON q.quotation_id = o.quotation_id
        """,
        """
        UPDATE orders o
        SET purchase_order_id = po.purchase_order_id
        FROM quotations q, purchase_orders po
        WHERE q.quotation_id = o.quotation_id
          AND po.supplier_id = q.supplier_id
          AND po.purchase_order_document_url IS NOT DISTINCT FROM o.purchase_order_document_url
        """,
        "ALTER TABLE orders ALTER COLUMN purchase_order_id SET NOT NULL",
        "ALTER TABLE orders ADD CONSTRAINT fk_orders_purchase_order_id FOREIGN KEY (purchase_order_id) REFERENCES purchase_orders (purchase_order_id)",
        "CREATE INDEX idx_orders_purchase_order_id ON orders (purchase_order_id)",
        "ALTER TABLE orders DROP COLUMN IF EXISTS purchase_order_document_url",
    ]
    for statement in statements:
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    bind = op.get_bind()
    statements = [
        "ALTER TABLE orders ADD COLUMN purchase_order_document_url TEXT",
        """
        UPDATE orders o
        SET purchase_order_document_url = po.purchase_order_document_url
        FROM purchase_orders po
        WHERE po.purchase_order_id = o.purchase_order_id
        """,
        "DROP INDEX IF EXISTS idx_orders_purchase_order_id",
        "ALTER TABLE orders DROP CONSTRAINT IF EXISTS fk_orders_purchase_order_id",
        "ALTER TABLE orders DROP COLUMN IF EXISTS purchase_order_id",
        "DROP TABLE IF EXISTS purchase_orders",
    ]
    for statement in statements:
        bind.exec_driver_sql(statement)
