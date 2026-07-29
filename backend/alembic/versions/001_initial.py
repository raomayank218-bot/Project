"""Initial schema — all tables from spec Section 8.

Revision ID: 001
Create Date: 2026-01-01
"""
from alembic import op
import sqlalchemy as sa

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── instruments ──────────────────────────────────────────────────────
    op.create_table('instruments',
        sa.Column('id', sa.String(20), primary_key=True),
        sa.Column('isin', sa.String(12), unique=True, nullable=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('asset_class', sa.String(50), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('exchange', sa.String(20), nullable=False),
        sa.Column('sector', sa.String(100), nullable=True),
        sa.Column('geography', sa.String(100), nullable=True),
        sa.Column('lot_size', sa.Numeric(18, 4), nullable=False),
        sa.Column('tick_size', sa.Numeric(18, 4), nullable=False),
        sa.Column('is_tradable', sa.Boolean, nullable=False),
        sa.Column('is_restricted', sa.Boolean, nullable=False),
        sa.Column('restrict_reason', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    # ── users ─────────────────────────────────────────────────────────────
    op.create_table('users',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('username', sa.String(100), unique=True, nullable=False),
        sa.Column('email', sa.String(200), unique=True, nullable=False),
        sa.Column('hashed_password', sa.String(200), nullable=False),
        sa.Column('full_name', sa.String(200), nullable=False),
        sa.Column('role', sa.String(30), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='ACTIVE'),
        sa.Column('mfa_enabled', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('client_id', sa.String(36), nullable=True),
        sa.Column('failed_logins', sa.String(5), nullable=False, server_default='0'),
        sa.Column('last_login', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    # ── accounts ──────────────────────────────────────────────────────────
    op.create_table('accounts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('client_id', sa.String(36), nullable=False),
        sa.Column('account_name', sa.String(200), nullable=False),
        sa.Column('account_type', sa.String(50), nullable=False),
        sa.Column('base_currency', sa.String(3), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='ACTIVE'),
        sa.Column('is_paper', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('credit_limit', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('daily_notional_limit', sa.Numeric(18, 2), nullable=False, server_default='5000000'),
        sa.Column('max_position_pct', sa.Numeric(5, 2), nullable=False, server_default='25.0'),
        sa.Column('cash_settled', sa.Numeric(18, 2), nullable=False, server_default='100000'),
        sa.Column('cash_unsettled', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_accounts_client_id', 'accounts', ['client_id'])

    # ── orders ────────────────────────────────────────────────────────────
    op.create_table('orders',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('client_order_id', sa.String(100), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('parent_order_id', sa.String(36), nullable=True),
        sa.Column('account_id', sa.String(36), nullable=False),
        sa.Column('entering_user_id', sa.String(36), nullable=False),
        sa.Column('beneficiary_account_id', sa.String(36), nullable=True),
        sa.Column('source', sa.String(20), nullable=False, server_default='GUI'),
        sa.Column('is_paper', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('instrument_id', sa.String(20), nullable=False),
        sa.Column('side', sa.String(4), nullable=False),
        sa.Column('order_type', sa.String(15), nullable=False),
        sa.Column('quantity', sa.Numeric(18, 4), nullable=False),
        sa.Column('price', sa.Numeric(18, 4), nullable=True),
        sa.Column('stop_price', sa.Numeric(18, 4), nullable=True),
        sa.Column('time_in_force', sa.String(3), nullable=False, server_default='DAY'),
        sa.Column('filled_quantity', sa.Numeric(18, 4), nullable=False, server_default='0'),
        sa.Column('avg_fill_price', sa.Numeric(18, 4), nullable=True),
        sa.Column('remaining_qty', sa.Numeric(18, 4), nullable=True),
        sa.Column('state', sa.String(30), nullable=False, server_default='RECEIVED'),
        sa.Column('reject_reason', sa.Text, nullable=True),
        sa.Column('cancel_reason', sa.Text, nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('validated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('risk_approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('working_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('filled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('settled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('commission', sa.Numeric(18, 4), nullable=True),
        sa.Column('exchange_fee', sa.Numeric(18, 4), nullable=True),
        sa.Column('tax', sa.Numeric(18, 4), nullable=True),
        sa.Column('net_consideration', sa.Numeric(18, 4), nullable=True),
    )
    op.create_index('ix_orders_account_id', 'orders', ['account_id'])
    op.create_index('ix_orders_instrument_id', 'orders', ['instrument_id'])
    op.create_index('ix_orders_state', 'orders', ['state'])
    op.create_index('ix_orders_client_order_id', 'orders', ['client_order_id'])

    # ── fills ─────────────────────────────────────────────────────────────
    op.create_table('fills',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('order_id', sa.String(36), nullable=False),
        sa.Column('account_id', sa.String(36), nullable=False),
        sa.Column('instrument_id', sa.String(20), nullable=False),
        sa.Column('side', sa.String(4), nullable=False),
        sa.Column('quantity', sa.Numeric(18, 4), nullable=False),
        sa.Column('price', sa.Numeric(18, 4), nullable=False),
        sa.Column('venue', sa.String(50), nullable=False),
        sa.Column('is_paper', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('commission', sa.Numeric(18, 4), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_fills_order_id', 'fills', ['order_id'])
    op.create_index('ix_fills_account_id', 'fills', ['account_id'])

    # ── trades ────────────────────────────────────────────────────────────
    op.create_table('trades',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('order_id', sa.String(36), nullable=False),
        sa.Column('account_id', sa.String(36), nullable=False),
        sa.Column('instrument_id', sa.String(20), nullable=False),
        sa.Column('side', sa.String(4), nullable=False),
        sa.Column('quantity', sa.Numeric(18, 4), nullable=False),
        sa.Column('price', sa.Numeric(18, 4), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('gross_consideration', sa.Numeric(18, 4), nullable=False),
        sa.Column('commission', sa.Numeric(18, 4), nullable=False),
        sa.Column('exchange_fee', sa.Numeric(18, 4), nullable=False),
        sa.Column('tax', sa.Numeric(18, 4), nullable=False),
        sa.Column('net_consideration', sa.Numeric(18, 4), nullable=False),
        sa.Column('settlement_date', sa.String(10), nullable=False),
        sa.Column('settlement_status', sa.String(30), nullable=False, server_default='PENDING'),
        sa.Column('entering_user_id', sa.String(36), nullable=False),
        sa.Column('beneficiary_account_id', sa.String(36), nullable=True),
        sa.Column('source_channel', sa.String(20), nullable=True),
        sa.Column('is_paper', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('trade_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_trades_account_id', 'trades', ['account_id'])
    op.create_index('ix_trades_instrument_id', 'trades', ['instrument_id'])
    op.create_index('ix_trades_order_id', 'trades', ['order_id'])

    # ── positions ─────────────────────────────────────────────────────────
    op.create_table('positions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('account_id', sa.String(36), nullable=False),
        sa.Column('instrument_id', sa.String(20), nullable=False),
        sa.Column('is_paper', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('quantity', sa.Numeric(18, 4), nullable=False, server_default='0'),
        sa.Column('settled_quantity', sa.Numeric(18, 4), nullable=False, server_default='0'),
        sa.Column('avg_cost', sa.Numeric(18, 4), nullable=False, server_default='0'),
        sa.Column('total_cost_basis', sa.Numeric(18, 4), nullable=False, server_default='0'),
        sa.Column('realised_pnl', sa.Numeric(18, 4), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_positions_account_id', 'positions', ['account_id'])
    op.create_index('ix_positions_account_instrument',
                    'positions', ['account_id', 'instrument_id', 'is_paper'], unique=True)

    # ── cash_movements ────────────────────────────────────────────────────
    op.create_table('cash_movements',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('account_id', sa.String(36), nullable=False),
        sa.Column('movement_type', sa.String(50), nullable=False),
        sa.Column('amount', sa.Numeric(18, 4), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('trade_id', sa.String(36), nullable=True),
        sa.Column('order_id', sa.String(36), nullable=True),
        sa.Column('is_settled', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('is_paper', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('value_date', sa.String(10), nullable=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_cash_movements_account_id', 'cash_movements', ['account_id'])

    # ── settlement_instructions ───────────────────────────────────────────
    op.create_table('settlement_instructions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('trade_id', sa.String(36), nullable=False),
        sa.Column('account_id', sa.String(36), nullable=False),
        sa.Column('instrument_id', sa.String(20), nullable=False),
        sa.Column('side', sa.String(4), nullable=False),
        sa.Column('quantity', sa.Numeric(18, 4), nullable=False),
        sa.Column('net_consideration', sa.Numeric(18, 4), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('settlement_date', sa.String(10), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='PENDING'),
        sa.Column('counterparty', sa.String(100), nullable=False),
        sa.Column('fail_reason', sa.Text, nullable=True),
        sa.Column('ageing_days', sa.Integer, nullable=False, server_default='0'),
        sa.Column('instructed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('matched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('settled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_settlement_instructions_trade_id', 'settlement_instructions', ['trade_id'])

    # ── trading_exceptions ────────────────────────────────────────────────
    op.create_table('trading_exceptions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('code', sa.String(10), nullable=False),
        sa.Column('severity', sa.String(10), nullable=False),
        sa.Column('status', sa.String(15), nullable=False, server_default='OPEN'),
        sa.Column('entity_type', sa.String(50), nullable=True),
        sa.Column('entity_id', sa.String(36), nullable=True),
        sa.Column('account_id', sa.String(36), nullable=True),
        sa.Column('instrument_id', sa.String(20), nullable=True),
        sa.Column('description', sa.Text, nullable=False),
        sa.Column('detail', sa.JSON, nullable=True),
        sa.Column('sla_hours', sa.Integer, nullable=False, server_default='24'),
        sa.Column('sla_due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('owner_user_id', sa.String(36), nullable=True),
        sa.Column('resolution_action', sa.Text, nullable=True),
        sa.Column('resolution_reason', sa.Text, nullable=True),
        sa.Column('resolved_by', sa.String(36), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('raised_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_trading_exceptions_code', 'trading_exceptions', ['code'])
    op.create_index('ix_trading_exceptions_status', 'trading_exceptions', ['status'])
    op.create_index('ix_trading_exceptions_entity_id', 'trading_exceptions', ['entity_id'])

    # ── audit_log (append-only) ───────────────────────────────────────────
    op.create_table('audit_log',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('sequence_num', sa.Integer, sa.Sequence('audit_seq'), nullable=False),
        sa.Column('correlation_id', sa.String(36), nullable=True),
        sa.Column('actor_type', sa.String(20), nullable=False),
        sa.Column('actor_id', sa.String(100), nullable=False),
        sa.Column('source_ip', sa.String(45), nullable=True),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=True),
        sa.Column('entity_id', sa.String(36), nullable=True),
        sa.Column('before_state', sa.JSON, nullable=True),
        sa.Column('after_state', sa.JSON, nullable=True),
        sa.Column('reason_code', sa.String(50), nullable=True),
        sa.Column('detail', sa.JSON, nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_audit_log_entity_id', 'audit_log', ['entity_id'])
    op.create_index('ix_audit_log_correlation_id', 'audit_log', ['correlation_id'])
    op.create_index('ix_audit_log_occurred_at', 'audit_log', ['occurred_at'])
    op.create_index('ix_audit_log_action', 'audit_log', ['action'])

    # ── prices (TimescaleDB hypertable) ───────────────────────────────────
    op.create_table('prices',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('instrument_id', sa.String(20), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), primary_key=True, nullable=False),
        sa.Column('interval_type', sa.String(10), nullable=False),
        sa.Column('open', sa.Numeric(18, 4), nullable=False),
        sa.Column('high', sa.Numeric(18, 4), nullable=False),
        sa.Column('low', sa.Numeric(18, 4), nullable=False),
        sa.Column('close', sa.Numeric(18, 4), nullable=False),
        sa.Column('volume', sa.Numeric(18, 0), nullable=False),
        sa.Column('adjusted_close', sa.Numeric(18, 4), nullable=True),
        sa.Column('dividend_amount', sa.Numeric(18, 4), nullable=True),
        sa.Column('split_coefficient', sa.Numeric(10, 4), nullable=True),
        sa.Column('source', sa.String(50), nullable=False),
        sa.Column('loaded_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_prices_instrument_timestamp', 'prices', ['instrument_id', 'timestamp'])

    # Convert to TimescaleDB hypertable (time-series optimisation)
    op.execute("SELECT create_hypertable('prices', 'timestamp', if_not_exists => TRUE);")

    # ── market_calendar ───────────────────────────────────────────────────
    op.create_table('market_calendar',
        sa.Column('trading_date', sa.String(10), primary_key=True),
        sa.Column('is_trading_day', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('session_open', sa.String(5), nullable=False, server_default='09:30'),
        sa.Column('session_close', sa.String(5), nullable=False, server_default='15:59'),
        sa.Column('notes', sa.Text, nullable=True),
    )

    # ── risk_limits ───────────────────────────────────────────────────────
    op.create_table('risk_limits',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('scope', sa.String(15), nullable=False),
        sa.Column('limit_type', sa.String(25), nullable=False),
        sa.Column('scope_id', sa.String(36), nullable=True),
        sa.Column('value', sa.Numeric(18, 4), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_by', sa.String(36), nullable=False),
        sa.Column('approved_by', sa.String(36), nullable=True),
        sa.Column('is_approved', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('effective_from', sa.String(10), nullable=True),
        sa.Column('effective_to', sa.String(10), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── sentiment_scores ──────────────────────────────────────────────────
    op.create_table('sentiment_scores',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('instrument_id', sa.String(20), nullable=False),
        sa.Column('score_date', sa.String(10), nullable=False),
        sa.Column('avg_score', sa.Numeric(6, 4), nullable=False),
        sa.Column('article_count', sa.Integer, nullable=False),
        sa.Column('label', sa.String(30), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_sentiment_instrument_date', 'sentiment_scores',
                    ['instrument_id', 'score_date'], unique=True)


def downgrade() -> None:
    for table in ['sentiment_scores', 'risk_limits', 'market_calendar', 'prices',
                  'audit_log', 'trading_exceptions', 'settlement_instructions',
                  'cash_movements', 'positions', 'trades', 'fills', 'orders',
                  'accounts', 'users', 'instruments']:
        op.drop_table(table)
