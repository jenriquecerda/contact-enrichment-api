"""Initial schema: contacts, enrichment jobs, resolved fields.

Revision ID: 0001
Revises:
Create Date: 2026-10-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

job_status = sa.Enum("queued", "running", "succeeded", "failed", name="job_status")


def upgrade() -> None:
    op.create_table(
        "contacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("company", sa.String(200)),
        sa.Column("email", sa.String(320)),
        sa.Column("domain", sa.String(253)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_contacts_email", "contacts", ["email"])
    op.create_index("ix_contacts_domain", "contacts", ["domain"])

    op.create_table(
        "enrichment_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "contact_id", sa.Uuid(), sa.ForeignKey("contacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", job_status, nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_enrichment_jobs_contact_id", "enrichment_jobs", ["contact_id"])

    op.create_table(
        "contact_fields",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "contact_id", sa.Uuid(), sa.ForeignKey("contacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id", sa.Uuid(), sa.ForeignKey("enrichment_jobs.id", ondelete="SET NULL")
        ),
        sa.Column("field", sa.String(50), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("conflict", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "resolved_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_contact_fields_contact_id", "contact_fields", ["contact_id"])


def downgrade() -> None:
    op.drop_table("contact_fields")
    op.drop_table("enrichment_jobs")
    op.drop_table("contacts")
    job_status.drop(op.get_bind(), checkfirst=True)
