import argparse
import asyncio
import getpass
import sys
from pathlib import Path
from typing import Optional

# Ensure root workspace is on path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(BASE_DIR / "photos_engine") not in sys.path:
    sys.path.insert(0, str(BASE_DIR / "photos_engine"))

from app.database import get_db, init_db
from app.security import hash_password


async def create_admin_user(username: str, password: str):
    """Create or update an administrator account in SQLite database."""
    await init_db()
    clean_username = username.strip()
    if not clean_username:
        print("[!] Error: Username cannot be empty.")
        sys.exit(1)
    if not password:
        print("[!] Error: Password cannot be empty.")
        sys.exit(1)

    pw_hash = hash_password(password)

    from sqlalchemy import select
    from app.models import Admin

    async with get_db() as db:
        stmt = select(Admin).where(Admin.username == clean_username)
        res = await db.execute(stmt)
        admin = res.scalar_one_or_none()
        if admin:
            admin.password_hash = pw_hash
            admin.is_active = True
        else:
            admin = Admin(username=clean_username, password_hash=pw_hash, is_active=True)
            db.add(admin)

    print(f"[+] Administrator '{clean_username}' successfully created/updated!")


def handle_create_admin(args):
    """Handle createadmin command from CLI flags or interactive prompts."""
    username = args.username
    password = args.password

    if not username:
        username = input("Enter Admin Username: ").strip()

    if not password:
        password = getpass.getpass("Enter Admin Password: ").strip()
        confirm = getpass.getpass("Confirm Admin Password: ").strip()
        if password != confirm:
            print("[!] Error: Passwords do not match.")
            sys.exit(1)

    asyncio.run(create_admin_user(username, password))


def handle_init_db(args):
    """Initialize database tables and indexes."""
    asyncio.run(init_db())
    print("[+] Database schema successfully initialized with WAL mode.")


async def create_api_key_entry(name: str, days: Optional[int] = None) -> str:
    """Generate and store an API key via CLI."""
    await init_db()
    from datetime import datetime, timedelta, timezone
    from app.models import ApiKey
    from app.security import generate_api_key

    raw_key, prefix = generate_api_key()
    expires_at = datetime.now(timezone.utc) + timedelta(days=days) if days else None

    async with get_db() as db:
        new_key = ApiKey(key=raw_key, name=name, prefix=prefix, is_active=True, expires_at=expires_at)
        db.add(new_key)

    print(f"[+] Successfully generated API Key for '{name}'!")
    print(f"[+] API Key: {raw_key}")
    print(f"[!] Please copy and save this key now. It will not be shown again.")
    return raw_key


def handle_create_key(args):
    """Handle createkey CLI command."""
    name = args.name or input("Enter API Key label/name: ").strip()
    if not name:
        print("[!] Error: Key name cannot be empty.")
        sys.exit(1)
    asyncio.run(create_api_key_entry(name, args.days))


def handle_makemigrations(args):
    """Generate autodetected migration revision via Alembic."""
    import subprocess
    message = args.message or "auto migration"
    cmd = [sys.executable, "-m", "alembic", "revision", "--autogenerate", "-m", message]
    print(f"[*] Running: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=str(BASE_DIR))
    if res.returncode != 0:
        sys.exit(res.returncode)


def handle_migrate(args):
    """Apply database migrations up to head via Alembic."""
    import subprocess
    cmd = [sys.executable, "-m", "alembic", "upgrade", "head"]
    print(f"[*] Running: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=str(BASE_DIR))
    if res.returncode != 0:
        sys.exit(res.returncode)


def handle_runserver(args):
    """Run uvicorn server for FastAPI application with Loguru."""
    from app.logging_config import setup_logging, logger
    setup_logging()

    # Automatically apply pending database migrations on startup
    try:
        import subprocess
        logger.info("Checking and applying database migrations (alembic upgrade head)...")
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=str(BASE_DIR), check=True)
    except Exception as exc:
        logger.warning("Auto-migration encountered an issue (falling back to init_db): {}", exc)

    import uvicorn
    logger.info("Starting FastAPI server on http://{}:{}", args.host, args.port)
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload, log_config=None)


def main():
    parser = argparse.ArgumentParser(description="Google Photos Engine CLI Manager")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: createadmin (aliases: create-admin, create_admin)
    create_admin_parser = subparsers.add_parser(
        "createadmin",
        aliases=["create-admin", "create_admin"],
        help="Create a new administrator account",
    )
    create_admin_parser.add_argument("-u", "--username", help="Admin username")
    create_admin_parser.add_argument("-p", "--password", help="Admin password")
    create_admin_parser.set_defaults(func=handle_create_admin)

    # Command: createkey (aliases: create-key, create_key)
    create_key_parser = subparsers.add_parser(
        "createkey",
        aliases=["create-key", "create_key"],
        help="Generate a persistent API key for third-party scripts/integrations",
    )
    create_key_parser.add_argument("-n", "--name", help="Key name or label (e.g. 'Bot')")
    create_key_parser.add_argument("-d", "--days", type=int, help="Optional expiry in days")
    create_key_parser.set_defaults(func=handle_create_key)

    # Command: init-db
    init_db_parser = subparsers.add_parser("init-db", help="Initialize database schema")
    init_db_parser.set_defaults(func=handle_init_db)

    # Command: makemigrations (aliases: make-migrations)
    make_migrations_parser = subparsers.add_parser(
        "makemigrations",
        aliases=["make-migrations"],
        help="Generate a new Alembic migration revision",
    )
    make_migrations_parser.add_argument("-m", "--message", default="auto migration", help="Migration message/description")
    make_migrations_parser.set_defaults(func=handle_makemigrations)

    # Command: migrate
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Run pending Alembic database migrations",
    )
    migrate_parser.set_defaults(func=handle_migrate)

    # Command: runserver
    runserver_parser = subparsers.add_parser("runserver", help="Start the FastAPI development server")
    runserver_parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    runserver_parser.add_argument("--port", type=int, default=8000, help="Port number (default: 8000)")
    runserver_parser.add_argument("--reload", action="store_true", default=True, help="Enable auto-reload (default: True)")
    runserver_parser.add_argument("--no-reload", dest="reload", action="store_false", help="Disable auto-reload")
    runserver_parser.set_defaults(func=handle_runserver)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
