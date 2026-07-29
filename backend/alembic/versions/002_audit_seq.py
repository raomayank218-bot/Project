"""Give audit_log.sequence_num a database default.

Revision ID: 002
Revises: 001
"""
from alembic import op

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS audit_log_sequence_num_seq OWNED BY audit_log.sequence_num")
    op.execute("ALTER TABLE audit_log ALTER COLUMN sequence_num SET DEFAULT nextval('audit_log_sequence_num_seq')")


def downgrade() -> None:
    op.execute("ALTER TABLE audit_log ALTER COLUMN sequence_num DROP DEFAULT")
    op.execute("DROP SEQUENCE IF EXISTS audit_log_sequence_num_seq")
