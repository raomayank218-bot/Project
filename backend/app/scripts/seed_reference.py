"""
Seeds all reference data that is not in the simulation CSVs:
  - 7 instruments (from profiled data)
  - 1 user per role (8 roles total)
  - Live account + paper account per client
  - Global risk limits
  - Default fee schedule in risk_limits

Run with: python -m app.scripts.seed_reference
"""
import uuid
import logging
import psycopg2
from psycopg2.extras import execute_values
from passlib.context import CryptContext
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("seed")

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_conn():
    from app.config import get_settings
    return psycopg2.connect(get_settings().database_url_sync)


INSTRUMENTS = [
    ("AAPL", "US0378331005", "Apple Inc.",           "EQUITY", "USD", "NASDAQ", "Technology",            "United States"),
    ("GOOG", "US02079K3059", "Alphabet Inc.",         "EQUITY", "USD", "NASDAQ", "Technology",            "United States"),
    ("IBM",  "US4592001014", "IBM Corp.",             "EQUITY", "USD", "NYSE",   "Technology",            "United States"),
    ("MSFT", "US5949181045", "Microsoft Corp.",       "EQUITY", "USD", "NASDAQ", "Technology",            "United States"),
    ("TSLA", "US88160R1014", "Tesla Inc.",            "EQUITY", "USD", "NASDAQ", "Consumer Discretionary","United States"),
    ("UL",   "GB00B10RZP78", "Unilever PLC",         "EQUITY", "USD", "NYSE",   "Consumer Staples",      "United Kingdom"),
    ("WMT",  "US9311421039", "Walmart Inc.",          "EQUITY", "USD", "NYSE",   "Consumer Staples",      "United States"),
]

# (username, email, full_name, role, client_id or None)
# client_id for CLIENT / AUTHORISED_REP users
CLIENT_A = str(uuid.uuid4())
CLIENT_B = str(uuid.uuid4())

USERS = [
    # Internal staff
    ("admin",      "admin@stp.internal",      "System Admin",         "ADMIN",          None),
    ("trader1",    "trader1@stp.internal",    "Alex Trader",          "TRADER",         None),
    ("ops1",       "ops1@stp.internal",       "Sam Operations",       "OPERATIONS",     None),
    ("risk1",      "risk1@stp.internal",      "Riley Risk",           "RISK",           None),
    ("compliance1","compliance1@stp.internal","Casey Compliance",     "COMPLIANCE",     None),
    ("readonly1",  "readonly1@stp.internal",  "Read Only User",       "READ_ONLY",      None),
    # Clients (persona P-01 from spec — the change-averse client)
    ("tom",        "tom@client-a.com",        "Tom Atkins",           "CLIENT",         CLIENT_A),
    ("patricia",   "patricia@client-a.com",   "Patricia Bose",        "CLIENT",         CLIENT_A),
    # Authorised rep (the secretary — persona P-02)
    ("secretary1", "secretary1@client-a.com", "Client A Secretary",   "AUTHORISED_REP", CLIENT_A),
    # Second client
    ("client_b",   "client_b@client-b.com",   "Self-Directed Trader", "CLIENT",         CLIENT_B),
]


def seed_instruments(cur):
    cur.execute("SELECT COUNT(*) FROM instruments")
    if cur.fetchone()[0] > 0:
        log.info("Instruments already seeded")
        return

    rows = [
        (ticker, isin, name, asset_class, currency, exchange, sector, geography,
         1, 0.01, True, False, None)
        for ticker, isin, name, asset_class, currency, exchange, sector, geography
        in INSTRUMENTS
    ]
    execute_values(cur, """
        INSERT INTO instruments
          (id, isin, name, asset_class, currency, exchange, sector, geography,
           lot_size, tick_size, is_tradable, is_restricted, restrict_reason)
        VALUES %s ON CONFLICT DO NOTHING
    """, rows)
    log.info(f"Seeded {len(rows)} instruments")


def seed_users(cur) -> dict:
    """Returns mapping of username -> user_id."""
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] > 0:
        log.info("Users already seeded")
        cur.execute("SELECT username, id FROM users")
        return {r[0]: r[1] for r in cur.fetchall()}

    user_map = {}
    rows = []
    for username, email, full_name, role, client_id in USERS:
        uid = str(uuid.uuid4())
        user_map[username] = uid
        rows.append((
            uid, username, email,
            pwd_ctx.hash("Password123!"),  # default dev password — change in prod
            full_name, role, "ACTIVE", False, client_id, "0"
        ))

    execute_values(cur, """
        INSERT INTO users
          (id, username, email, hashed_password, full_name, role, status,
           mfa_enabled, client_id, failed_logins)
        VALUES %s ON CONFLICT DO NOTHING
    """, rows)
    log.info(f"Seeded {len(rows)} users")
    return user_map


def seed_accounts(cur, user_map: dict) -> dict:
    """Returns mapping of account_name -> account_id."""
    cur.execute("SELECT COUNT(*) FROM accounts")
    if cur.fetchone()[0] > 0:
        log.info("Accounts already seeded")
        cur.execute("SELECT account_name, id FROM accounts")
        return {r[0]: r[1] for r in cur.fetchall()}

    account_map = {}
    rows = []

    def add_account(client_id, name, acct_type, is_paper, cash, daily_limit):
        aid = str(uuid.uuid4())
        account_map[name] = aid
        rows.append((aid, client_id, name, acct_type, "USD", "ACTIVE",
                     is_paper, 0, daily_limit, 25.0, cash, 0, None))
        return aid

    # Client A — live + paper accounts
    add_account(CLIENT_A, "Client-A-Live",  "CASH", False, 500_000, 5_000_000)
    add_account(CLIENT_A, "Client-A-Paper", "CASH", True,  100_000, 5_000_000)

    # Client B
    add_account(CLIENT_B, "Client-B-Live",  "CASH", False, 250_000, 2_000_000)
    add_account(CLIENT_B, "Client-B-Paper", "CASH", True,  100_000, 2_000_000)

    execute_values(cur, """
        INSERT INTO accounts
          (id, client_id, account_name, account_type, base_currency, status,
           is_paper, credit_limit, daily_notional_limit, max_position_pct,
           cash_settled, cash_unsettled, notes)
        VALUES %s ON CONFLICT DO NOTHING
    """, rows)
    log.info(f"Seeded {len(rows)} accounts")
    return account_map


def seed_risk_limits(cur, admin_id: str):
    cur.execute("SELECT COUNT(*) FROM risk_limits")
    if cur.fetchone()[0] > 0:
        log.info("Risk limits already seeded")
        return

    limits = [
        # (scope, limit_type, scope_id, value, currency)
        ("GLOBAL", "DAILY_NOTIONAL",      None, 10_000_000, "USD"),
        ("GLOBAL", "FAT_FINGER_PRICE",    None, 10.0,       "USD"),  # % deviation
        ("GLOBAL", "FAT_FINGER_NOTIONAL", None, 1_000_000,  "USD"),
        ("GLOBAL", "POSITION_SIZE",       None, 10_000,     "USD"),  # max shares
        ("GLOBAL", "CONCENTRATION_PCT",   None, 25.0,       "USD"),  # % of portfolio
    ]

    rows = [
        (str(uuid.uuid4()), scope, ltype, scope_id, value, currency,
         True, admin_id, admin_id, True)  # pre-approved defaults
        for scope, ltype, scope_id, value, currency in limits
    ]
    execute_values(cur, """
        INSERT INTO risk_limits
          (id, scope, limit_type, scope_id, value, currency,
           is_active, created_by, approved_by, is_approved)
        VALUES %s ON CONFLICT DO NOTHING
    """, rows)
    log.info(f"Seeded {len(rows)} global risk limits")


def seed_audit_entry(cur, actor_id: str, action: str, detail: dict):
    """Write a seed-time audit entry."""
    import json
    cur.execute("""
        INSERT INTO audit_log (id, actor_type, actor_id, action, detail)
        VALUES (%s, %s, %s, %s, %s)
    """, (str(uuid.uuid4()), "SYSTEM", actor_id, action, json.dumps(detail)))


def main():
    log.info("=== Seeding reference data ===")
    conn = get_conn()
    cur = conn.cursor()
    try:
        seed_instruments(cur)
        user_map = seed_users(cur)
        account_map = seed_accounts(cur, user_map)
        admin_id = user_map.get("admin", "SYSTEM")
        seed_risk_limits(cur, admin_id)

        # Audit trail entry for the seed operation
        seed_audit_entry(cur, "SYSTEM", "REFERENCE_DATA_SEEDED", {
            "instruments": len(INSTRUMENTS),
            "users": len(USERS),
            "accounts": len(account_map),
        })

        conn.commit()
        log.info("=== Reference data seeding complete ===")
        log.info("Default credentials: username / Password123!")
        log.info("Users: admin, trader1, ops1, risk1, compliance1, readonly1, tom, patricia, secretary1, client_b")
    except Exception as e:
        conn.rollback()
        log.error(f"Seeding failed: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
