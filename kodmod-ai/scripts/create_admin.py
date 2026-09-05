"""
Create an administrator account.

The first admin cannot be created through the API: registration needs an
invitation code, and only an admin can mint one. This script breaks that
circle. Run it once after the first `make migrate`::

    python -m scripts.create_admin --username admin

You will be prompted for a password. Pass --password to supply it directly
(for CI or a scripted setup), knowing it will land in your shell history.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from api.security import hash_password
from database.models import User
from database.session import async_session, close_db, init_db


async def _create(username: str, password: str, full_name: str) -> int:
    await init_db()
    try:
        async with async_session() as session:
            existing = (
                await session.execute(select(User).where(User.username == username))
            ).scalar_one_or_none()

            if existing is not None:
                if existing.role == "admin":
                    existing.password_hash = hash_password(password)
                    await session.commit()
                    print(f"Reset the password for existing admin '{username}'.")
                    return 0
                print(
                    f"'{username}' already exists with role '{existing.role}'. "
                    "Choose a different username.",
                    file=sys.stderr,
                )
                return 1

            session.add(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    role="admin",
                    full_name=full_name,
                )
            )
            await session.commit()
        print(f"Created admin '{username}'.")
        return 0
    finally:
        await close_db()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or reset an admin account.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", default=None, help="Prompted for if omitted.")
    parser.add_argument("--full-name", default=None)
    args = parser.parse_args()

    username = args.username.strip().lower()
    password = args.password or getpass.getpass("Password: ")
    if not args.password:
        if password != getpass.getpass("Confirm password: "):
            print("Passwords did not match.", file=sys.stderr)
            return 1

    try:
        hash_password(password)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    return asyncio.run(_create(username, password, args.full_name or username))


if __name__ == "__main__":
    raise SystemExit(main())
