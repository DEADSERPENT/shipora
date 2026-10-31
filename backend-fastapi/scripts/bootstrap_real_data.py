"""One-off setup of the REAL (non-demo) data in the configured MongoDB: the first operations (admin) account and the
public support contact details.

    cd backend-fastapi
    .venv/Scripts/python.exe scripts/bootstrap_real_data.py \
        --admin-name "Your Name" --admin-email you@company.com --organization "Shipora" \
        --phone "+91 ..." --support-email support@company.com --whatsapp "+91 ..." \
        --address "Office address" --hours "Mon – Sat · 8 AM – 8 PM"

The admin password is read from a hidden prompt (or BOOTSTRAP_ADMIN_PASSWORD) so it never lands in shell history or a
chat. Re-running is safe: an existing admin with the same e-mail is left untouched and the support details are
updated in place. It refuses to run when MongoDB is unreachable (it would otherwise write to the throw-away
in-memory fallback), and it never creates demo data."""

import argparse
import asyncio
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database  # noqa: E402
from auth_utils import hash_password  # noqa: E402
from models.admin import Admin  # noqa: E402
from models.support_config import SupportConfig  # noqa: E402
from validation import Email, Name, OptionalText, Password  # noqa: E402
from pydantic import TypeAdapter  # noqa: E402


def _check(adapter_type, value, label):
    try:
        return TypeAdapter(adapter_type).validate_python(value)
    except Exception as err:
        sys.exit(f"{label} is not valid: {err}")


async def bootstrap(admin_name, admin_email, password, organization, support) -> dict:
    """Create the admin (if absent) and upsert the support config. Returns what it did, never any secret."""
    result = {}
    email = admin_email.lower()
    if await Admin.find_one(Admin.email == email):
        result["admin"] = "already exists - left untouched"
    else:
        await Admin(name=admin_name, email=email, password=hash_password(password), organization=organization).insert()
        result["admin"] = "created"

    doc = await SupportConfig.find_one(SupportConfig.singleton == "config")
    fields = {k: v for k, v in support.items() if v}
    if doc is None:
        await SupportConfig(**fields).insert()
        result["support"] = "created"
    else:
        for k, v in fields.items():
            setattr(doc, k, v)
        await doc.save()
        result["support"] = "updated"
    return result


async def main(args) -> None:
    await database.connect_db()
    if database.IN_MEMORY:
        sys.exit("MongoDB is not reachable, so this would only write to a throw-away in-memory database. Aborting.")

    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD") or getpass.getpass("Admin password (hidden): ")
    if not os.environ.get("BOOTSTRAP_ADMIN_PASSWORD") and getpass.getpass("Repeat password: ") != password:
        sys.exit("Passwords do not match.")

    result = await bootstrap(
        _check(Name, args.admin_name, "Admin name"),
        _check(Email, args.admin_email, "Admin e-mail"),
        _check(Password, password, "Password"),
        _check(OptionalText, args.organization, "Organization"),
        {
            "phone": args.phone, "email": args.support_email, "whatsapp": args.whatsapp,
            "officeAddress": args.address, "officeHours": args.hours,
        },
    )
    sys.stdout.write(f"Admin account : {result['admin']}\nSupport config: {result['support']}\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--admin-name", required=True)
    p.add_argument("--admin-email", required=True)
    p.add_argument("--organization", default="")
    p.add_argument("--phone")
    p.add_argument("--support-email")
    p.add_argument("--whatsapp")
    p.add_argument("--address")
    p.add_argument("--hours")
    asyncio.run(main(p.parse_args()))
