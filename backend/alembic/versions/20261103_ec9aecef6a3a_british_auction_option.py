"""British auction option

The brief creates an RFQ "with the British Auction option enabled", so the
option is a column. With it off, an RFQ is a plain one: it closes at its bid
close time, is never extended, and has no X, Y or trigger.

Existing rows were all British auctions, so they keep the option on.

Revision ID: ec9aecef6a3a
Revises: 4251f99e8609
Create Date: 2026-11-03 22:59:46.994276

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ec9aecef6a3a"
down_revision: str | Sequence[str] | None = "4251f99e8609"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONFIG_MATCHES_OPTION = (
    "(is_british_auction AND trigger_window_minutes IS NOT NULL"
    " AND extension_minutes IS NOT NULL AND trigger_type IS NOT NULL)"
    " OR (NOT is_british_auction AND trigger_window_minutes IS NULL"
    " AND extension_minutes IS NULL AND trigger_type IS NULL)"
)
ONLY_BRITISH_EXTENDS = (
    "is_british_auction OR (current_close_at = bid_close_at AND extension_count = 0)"
)


def upgrade() -> None:
    op.add_column(
        "rfqs",
        sa.Column(
            "is_british_auction", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
    )
    op.alter_column("rfqs", "trigger_window_minutes", existing_type=sa.INTEGER(), nullable=True)
    op.alter_column("rfqs", "extension_minutes", existing_type=sa.INTEGER(), nullable=True)
    op.alter_column("rfqs", "trigger_type", existing_type=sa.VARCHAR(length=32), nullable=True)
    # op.f(): these are the final names; don't apply the naming convention again.
    op.create_check_constraint(
        op.f("ck_rfqs_auction_config_matches_option"), "rfqs", CONFIG_MATCHES_OPTION
    )
    op.create_check_constraint(
        op.f("ck_rfqs_only_british_auction_extends"), "rfqs", ONLY_BRITISH_EXTENDS
    )


def downgrade() -> None:
    # Plain RFQs have no X, Y or trigger, which the old schema cannot hold.
    op.execute("DELETE FROM rfqs WHERE NOT is_british_auction")
    op.drop_constraint(op.f("ck_rfqs_only_british_auction_extends"), "rfqs", type_="check")
    op.drop_constraint(op.f("ck_rfqs_auction_config_matches_option"), "rfqs", type_="check")
    op.alter_column("rfqs", "trigger_type", existing_type=sa.VARCHAR(length=32), nullable=False)
    op.alter_column("rfqs", "extension_minutes", existing_type=sa.INTEGER(), nullable=False)
    op.alter_column("rfqs", "trigger_window_minutes", existing_type=sa.INTEGER(), nullable=False)
    op.drop_column("rfqs", "is_british_auction")
