from typing import Any, Dict, Literal, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth_utils import get_current_user, hash_password, sign_token
from models.admin import Admin
from models.driver import Driver
from models.user import Location, User
from serializers import admin_payload, admin_profile_json, driver_payload, driver_profile_json, user_payload, user_profile_json

router = APIRouter(prefix="/api/auth", tags=["Auth"])


def _model_for(role: Optional[str]):
    return {"driver": Driver, "admin": Admin}.get(role, User)


# ─── Register ──────────────────────────────────────────────────────────────
class RegisterUserBody(BaseModel):
    name: str
    email: str
    password: str = Field(min_length=6)
    phone: str
    address: str
    location: Location
    wasteType: Literal["household", "recyclable", "organic", "mixed"] = "mixed"
    pickupSchedule: Literal["daily", "alternate", "weekly"] = "daily"
    residentType: Literal["house", "flat"] = "house"


@router.post("/register/user", status_code=201, summary="Register a resident")
async def register_user(body: RegisterUserBody):
    if await User.find_one(User.email == body.email.lower()):
        raise HTTPException(status_code=400, detail="Email already registered")

    data = body.model_dump(exclude={"password"})
    user = User(**data, password=hash_password(body.password))
    await user.insert()
    payload = user_payload(user)
    return {"token": sign_token(payload), "user": payload}


class RegisterDriverBody(BaseModel):
    name: str
    email: str
    password: str = Field(min_length=6)
    phone: str
    vehicleNo: str
    licenseNo: str
    assignedArea: str


@router.post("/register/driver", status_code=201, summary="Register a driver")
async def register_driver(body: RegisterDriverBody):
    if await Driver.find_one(Driver.email == body.email.lower()):
        raise HTTPException(status_code=400, detail="Email already registered")

    data = body.model_dump(exclude={"password"})
    driver = Driver(**data, password=hash_password(body.password))
    await driver.insert()
    payload = driver_payload(driver)
    return {"token": sign_token(payload), "user": payload}


class RegisterAdminBody(BaseModel):
    name: str
    email: str
    password: str = Field(min_length=6)
    organization: str = ""


@router.post("/register/admin", status_code=201, summary="Register an admin")
async def register_admin(body: RegisterAdminBody):
    if await Admin.find_one(Admin.email == body.email.lower()):
        raise HTTPException(status_code=400, detail="Email already registered")

    data = body.model_dump(exclude={"password"})
    admin = Admin(**data, password=hash_password(body.password))
    await admin.insert()
    payload = admin_payload(admin)
    return {"token": sign_token(payload), "user": payload}


# ─── Login ─────────────────────────────────────────────────────────────────
class LoginBody(BaseModel):
    email: str
    password: str
    role: Optional[Literal["user", "driver", "admin"]] = "user"


@router.post("/login", summary="Login (all roles)")
async def login(body: LoginBody):
    Model = _model_for(body.role)
    account = await Model.find_one(Model.email == body.email.lower())
    if not account or not account.compare_password(body.password):
        raise HTTPException(status_code=400, detail="Invalid credentials")

    payload = {
        "user": user_payload,
        "driver": driver_payload,
        "admin": admin_payload,
    }[body.role or "user"](account)
    return {"token": sign_token(payload), "user": payload}


# ─── Profile ───────────────────────────────────────────────────────────────
@router.get("/profile", summary="Get full profile")
async def get_profile(current_user: dict = Depends(get_current_user)):
    Model = _model_for(current_user["role"])
    doc = await Model.get(PydanticObjectId(current_user["id"]))
    if not doc:
        raise HTTPException(status_code=404, detail="Account not found")
    profile_fn = {"user": user_profile_json, "driver": driver_profile_json, "admin": admin_profile_json}[current_user["role"]]
    return profile_fn(doc)


ALLOWED_FIELDS = {
    "user": ["name", "phone", "address", "location", "wasteType", "pickupSchedule", "residentType"],
    "driver": ["name", "phone", "assignedArea"],
    "admin": ["name", "organization"],
}


@router.put("/profile", summary="Update profile")
async def update_profile(body: Dict[str, Any], current_user: dict = Depends(get_current_user)):
    role = current_user["role"]
    Model = _model_for(role)
    doc = await Model.get(PydanticObjectId(current_user["id"]))
    if not doc:
        raise HTTPException(status_code=404, detail="Account not found")

    for field in ALLOWED_FIELDS[role]:
        if field in body:
            value = Location(**body[field]) if field == "location" else body[field]
            setattr(doc, field, value)
    await doc.save()

    profile_fn = {"user": user_profile_json, "driver": driver_profile_json, "admin": admin_profile_json}[role]
    return profile_fn(doc)


# ─── Password flows ────────────────────────────────────────────────────────
class ForgotPasswordBody(BaseModel):
    email: str
    role: Optional[Literal["user", "driver", "admin"]] = "user"


@router.post("/forgot-password", summary="Verify email exists for password reset")
async def forgot_password(body: ForgotPasswordBody):
    Model = _model_for(body.role)
    account = await Model.find_one(Model.email == body.email.lower())
    if not account:
        raise HTTPException(status_code=404, detail="No account found with this email for the selected role.")
    return {"message": "Account verified. You can now set a new password."}


class ResetPasswordBody(BaseModel):
    email: str
    role: Optional[Literal["user", "driver", "admin"]] = "user"
    newPassword: str


@router.post("/reset-password", summary="Reset password")
async def reset_password(body: ResetPasswordBody):
    if len(body.newPassword) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    Model = _model_for(body.role)
    account = await Model.find_one(Model.email == body.email.lower())
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")
    account.password = hash_password(body.newPassword)
    await account.save()
    return {"message": "Password reset successfully. You can now log in."}


class ChangePasswordBody(BaseModel):
    currentPassword: str
    newPassword: str


@router.post("/change-password", summary="Change password (requires current password)")
async def change_password(body: ChangePasswordBody, current_user: dict = Depends(get_current_user)):
    if len(body.newPassword) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters.")
    Model = _model_for(current_user["role"])
    account = await Model.get(PydanticObjectId(current_user["id"]))
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")
    if not account.compare_password(body.currentPassword):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    account.password = hash_password(body.newPassword)
    await account.save()
    return {"message": "Password changed successfully."}
