"""Track job attempts and source errors; keep field history with an is_current flag.

Retries needed an attempt counter, and re-enrichment was overwriting what a
field used to be. Existing rows are backfilled so only the newest row per
(contact, field) stays current.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "enrichment_jobs",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "enrichment_jobs",
        sa.Column("source_errors", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "contact_fields",
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    # Backfill: only the most recent row per (contact, field) is current.
    op.execute(
        """
        UPDATE contact_fields AS cf
        SET is_current = FALSE
        WHERE EXISTS (
            SELECT 1 FROM contact_fields newer
            WHERE newer.contact_id = cf.contact_id
              AND newer.field = cf.field
              AND (newer.resolved_at, newer.id) > (cf.resolved_at, cf.id)
        )
        """
    )

    # At most one current value per contact and field.
    op.create_index(
        "uq_contact_fields_current",
        "contact_fields",
        ["contact_id", "field"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    # The worker looks for open jobs per contact; keep that lookup cheap.
    op.create_index(
        "ix_enrichment_jobs_contact_status", "enrichment_jobs", ["contact_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_enrichment_jobs_contact_status", table_name="enrichment_jobs")
    op.drop_index("uq_contact_fields_current", table_name="contact_fields")
    op.drop_column("contact_fields", "is_current")
    op.drop_column("enrichment_jobs", "source_errors")
    op.drop_column("enrichment_jobs", "attempts")
