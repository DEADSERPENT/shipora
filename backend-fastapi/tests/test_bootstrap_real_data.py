"""scripts/bootstrap_real_data.py: first admin + support details, idempotent, no demo data, password stored hashed."""
import importlib.util
import os

import pytest

from models.admin import Admin
from models.delivery_agent import DeliveryAgent
from models.support_config import SupportConfig

pytestmark = pytest.mark.anyio

_spec = importlib.util.spec_from_file_location(
    "bootstrap_real_data", os.path.join(os.path.dirname(__file__), "..", "scripts", "bootstrap_real_data.py"))
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

SUPPORT = {"phone": "+91 80 1111 2222", "email": "help@shipora.example", "whatsapp": "", "officeAddress": "1 MG Road, Bengaluru", "officeHours": ""}


async def test_creates_admin_and_support_without_demo_data(client):
    await Admin.find_all().delete()
    await SupportConfig.find_all().delete()
    out = await script.bootstrap("Real Admin", "Real.Admin@Example.com", "S3cure-pass!", "Shipora", SUPPORT)
    assert out == {"admin": "created", "support": "created"}

    admin = await Admin.find_one(Admin.email == "real.admin@example.com")
    assert admin and admin.password != "S3cure-pass!" and admin.compare_password("S3cure-pass!")
    cfg = await SupportConfig.find_one(SupportConfig.singleton == "config")
    assert cfg.phone == "+91 80 1111 2222" and cfg.email == "help@shipora.example"
    assert cfg.whatsapp == SupportConfig().whatsapp  # blank values keep the model default instead of blanking the field
    assert await DeliveryAgent.find_all().count() == 0  # never seeds demo agents/customers/shipments


async def test_is_idempotent_and_never_overwrites_an_existing_admin(client):
    await Admin.find_all().delete()
    await SupportConfig.find_all().delete()
    await script.bootstrap("Real Admin", "a@example.com", "S3cure-pass!", "Shipora", SUPPORT)
    out = await script.bootstrap("Someone Else", "a@example.com", "Different-pass1!", "Other", {**SUPPORT, "phone": "+91 80 9999 0000"})
    assert out == {"admin": "already exists - left untouched", "support": "updated"}
    assert await Admin.find_all().count() == 1
    admin = await Admin.find_one(Admin.email == "a@example.com")
    assert admin.name == "Real Admin" and admin.compare_password("S3cure-pass!")
    assert (await SupportConfig.find_one(SupportConfig.singleton == "config")).phone == "+91 80 9999 0000"
