"""Creates a demo organization with users and synthetic customers.

    python -m scripts.seed            # uses DATABASE_URL
    python -m scripts.seed --customers 200

All data is fictional (generated names, example.com addresses).
"""

import argparse
import asyncio
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import create_engine, create_session_factory
from app.models import Customer, CustomerStatus, Organization, Role, User

FIRST = ["Asha", "Ben", "Chen", "Dana", "Elif", "Farid", "Grace", "Hiro", "Isla", "Jonas", "Kavya", "Liam", "Maya", "Nikhil"]
LAST = ["Rao", "Okafor", "Wei", "Silva", "Kaya", "Haddad", "Lee", "Tanaka", "Murphy", "Berg", "Iyer", "Walsh", "Cohen", "Menon"]
COMPANIES = ["Northwind", "Contoso", "Fabrikam", "Globex", "Initech", "Umbrella Labs", "Tailspin", "Wingtip", None]
DEMO_PASSWORD = "demo-password-change-me"


async def seed(customer_count: int) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    rng = random.Random(42)  # deterministic, so screenshots and tests are reproducible

    async with factory() as session:
        if await session.scalar(select(Organization).where(Organization.slug == "demo-co")):
            print("Demo data already present (organization slug 'demo-co').")
            return

        organization = Organization(name="Demo Co", slug="demo-co")
        users = [
            User(organization=organization, email="owner@demo.example.com", full_name="Olivia Owner", role=Role.OWNER),
            User(organization=organization, email="admin@demo.example.com", full_name="Arjun Admin", role=Role.ADMIN),
            User(organization=organization, email="member@demo.example.com", full_name="Mei Member", role=Role.MEMBER),
        ]
        password_hash = hash_password(DEMO_PASSWORD)
        for user in users:
            user.password_hash = password_hash
        session.add_all([organization, *users])
        await session.flush()

        now = datetime.now(UTC)
        for index in range(customer_count):
            first, last = rng.choice(FIRST), rng.choice(LAST)
            status = rng.choices(list(CustomerStatus), weights=[3, 5, 2])[0]
            session.add(
                Customer(
                    organization_id=organization.id,
                    name=f"{first} {last}",
                    email=f"{first.lower()}.{last.lower()}{index}@customers.example.com",
                    company=rng.choice(COMPANIES),
                    status=status,
                    lifetime_value=Decimal(rng.randint(0, 500_000)) / 100 if status is not CustomerStatus.LEAD else Decimal("0"),
                    owner_id=rng.choice(users).id,
                    created_at=now - timedelta(days=rng.randint(0, 365)),
                )
            )
        await session.commit()

    await engine.dispose()
    print(f"Created organization 'Demo Co', 3 users (password: {DEMO_PASSWORD}) and {customer_count} customers.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--customers", type=int, default=120)
    asyncio.run(seed(parser.parse_args().customers))
