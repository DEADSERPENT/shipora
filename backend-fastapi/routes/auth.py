import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import jwt
from beanie import PydanticObjectId
from pymongo.errors import DuplicateKeyError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

import config
import database
import ratelimit
from auth_utils import _secret, get_current_user, hash_password, sign_token
from models.admin import Admin
from models.customer import Customer, Location
from models.delivery_agent import DeliveryAgent
from serializers import admin_payload, admin_profile_json, driver_payload, driver_profile_json, user_payload, user_profile_json
from validation import Address, Email, Name, OptionalText, Password, Phone, ShortText

router = APIRouter(prefix="/api/auth", tags=["Auth"])
log = logging.getLogger("shipora.auth")

RESET_TOKEN_MINUTES = 15


def _model_for(role: Optional[str]):
    return {"driver": DeliveryAgent, "admin": Admin}.get(role, Customer)


# ─── Register ──────────────────────────────────────────────────────────────
async def _insert_unique(doc) -> None:
    """Insert a new account; two simultaneous sign-ups with one e-mail get the same clean 400 (the unique index decides)."""
    try:
        await doc.insert()
    except DuplicateKeyError:
        raise HTTPException(status_code=400, detail="Email already registered")


class RegisterUserBody(BaseModel):
    name: Name
    email: Email
    password: Password
    phone: Phone
    address: Address
    location: Location
    customerType: Literal["individual", "business"] = "individual"
    deliveryInstructions: OptionalText = ""


@router.post("/register/user", status_code=201, summary="Register a customer", dependencies=[Depends(ratelimit.limited("register"))])
async def register_user(body: RegisterUserBody):
    if await Customer.find_one(Customer.email == body.email.lower()):
        raise HTTPException(status_code=400, detail="Email already registered")

    data = body.model_dump(exclude={"password"})
    user = Customer(**data, password=hash_password(body.password))
    await _insert_unique(user)
    payload = user_payload(user)
    return {"token": sign_token(payload), "user": payload}


class RegisterDriverBody(BaseModel):
    name: Name
    email: Email
    password: Password
    phone: Phone
    vehicleNo: ShortText
    vehicleType: Literal["bike", "van", "truck"] = "van"
    licenseNo: ShortText
    assignedArea: ShortText


@router.post("/register/driver", status_code=201, summary="Register a delivery agent", dependencies=[Depends(ratelimit.limited("register"))])
async def register_driver(body: RegisterDriverBody):
    if await DeliveryAgent.find_one(DeliveryAgent.email == body.email.lower()):
        raise HTTPException(status_code=400, detail="Email already registered")

    data = body.model_dump(exclude={"password"})
    driver = DeliveryAgent(**data, password=hash_password(body.password))
    await _insert_unique(driver)
    payload = driver_payload(driver)
    return {"token": sign_token(payload), "user": payload}


class RegisterAdminBody(BaseModel):
    name: Name
    email: Email
    password: Password
    organization: OptionalText = ""
    inviteCode: Optional[str] = Field(default=None, max_length=200)


def _admin_signup_allowed(invite_code: Optional[str]) -> bool:
    """Operations accounts grant full access, so sign-up is never open to the public in
    production: an ADMIN_SIGNUP_CODE must be configured and presented. In development
    (no code configured) it stays open so local setups work out of the box."""
    configured = config.admin_signup_code()
    if configured:
        return bool(invite_code) and secrets.compare_digest(invite_code.encode(), configured.encode())
    # No invite code configured: only the throw-away in-memory dev database may allow open sign-up. Against a real
    # MongoDB (Atlas/local) it stays closed — create the first admin with scripts/bootstrap_real_data.py.
    return not config.is_production() and not database.REAL_DB


@router.post("/register/admin", status_code=201, summary="Register an operations (admin) account", dependencies=[Depends(ratelimit.limited("register"))])
async def register_admin(body: RegisterAdminBody):
    if not _admin_signup_allowed(body.inviteCode):
        log.warning("admin signup refused", extra={"event": "admin_signup_refused"})
        raise HTTPException(status_code=403, detail="Operations accounts are created by invitation only.")
    if await Admin.find_one(Admin.email == body.email.lower()):
        raise HTTPException(status_code=400, detail="Email already registered")

    data = body.model_dump(exclude={"password", "inviteCode"})
    admin = Admin(**data, password=hash_password(body.password))
    await _insert_unique(admin)
    payload = admin_payload(admin)
    return {"token": sign_token(payload), "user": payload}


# ─── Login ─────────────────────────────────────────────────────────────────
class LoginBody(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)
    role: Optional[Literal["user", "driver", "admin"]] = "user"


@router.post("/login", summary="Login (all roles)")
async def login(body: LoginBody, request: Request):
    ratelimit.enforce(request, "login")                    # per client address
    ratelimit.check_account(request, body.email)           # per target account (failed attempts only), from any address
    Model = _model_for(body.role)
    account = await Model.find_one(Model.email == body.email.lower())
    if not account or not account.compare_password(body.password):
        ratelimit.record_failed_login(body.email)
        log.info("login failed", extra={"event": "login_failed", "role": body.role})
        raise HTTPException(status_code=400, detail="Invalid credentials")

    payload = {
        "user": user_payload,
        "driver": driver_payload,
        "admin": admin_payload,
    }[body.role or "user"](account)
    log.info("login ok", extra={"event": "login_ok", "role": body.role, "user_id": str(account.id)})
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


class _ProfileBase(BaseModel):
    model_config = ConfigDict(extra="ignore")  # role / email / password etc. in the body are silently dropped


class CustomerProfileUpdate(_ProfileBase):
    name: Optional[Name] = None
    phone: Optional[Phone] = None
    address: Optional[Address] = None
    location: Optional[Location] = None
    customerType: Optional[Literal["individual", "business"]] = None
    deliveryInstructions: Optional[OptionalText] = None


class AgentProfileUpdate(_ProfileBase):
    name: Optional[Name] = None
    phone: Optional[Phone] = None
    assignedArea: Optional[ShortText] = None
    vehicleType: Optional[Literal["bike", "van", "truck"]] = None
    availability: Optional[Literal["available", "on_delivery", "off_duty"]] = None


class AdminProfileUpdate(_ProfileBase):
    name: Optional[Name] = None
    organization: Optional[OptionalText] = None


PROFILE_MODELS = {"user": CustomerProfileUpdate, "driver": AgentProfileUpdate, "admin": AdminProfileUpdate}


@router.put("/profile", summary="Update profile")
async def update_profile(request: Request, current_user: dict = Depends(get_current_user)):
    role = current_user["role"]
    try:
        raw = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    # Validation errors surface as 422 via the app-wide handler; invalid values are never stored.
    try:
        updates = PROFILE_MODELS[role].model_validate(raw).model_dump(exclude_unset=True, exclude_none=True)
    except ValidationError as err:
        raise RequestValidationError(err.errors(include_url=False, include_context=False, include_input=False))

    Model = _model_for(role)
    doc = await Model.get(PydanticObjectId(current_user["id"]))
    if not doc:
        raise HTTPException(status_code=404, detail="Account not found")
    for field, value in updates.items():
        setattr(doc, field, Location(**value) if field == "location" else value)
    await doc.save()

    profile_fn = {"user": user_profile_json, "driver": driver_profile_json, "admin": admin_profile_json}[role]
    return profile_fn(doc)


# ─── Password flows ────────────────────────────────────────────────────────
def _password_fingerprint(account) -> str:
    """Changes whenever the password changes, which makes a reset token single-use."""
    return hashlib.sha256(account.password.encode()).hexdigest()[:16]


def make_reset_token(account, role: str) -> str:
    claims = {
        "purpose": "pwd_reset", "sub": str(account.id), "role": role, "pwf": _password_fingerprint(account),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_MINUTES),
    }
    return jwt.encode(claims, _secret(), algorithm="HS256")


def _check_reset_token(token: Optional[str], account, role: str) -> bool:
    if not token:
        return False
    try:
        c = jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return False
    return (c.get("purpose") == "pwd_reset" and c.get("sub") == str(account.id)
            and c.get("role") == role and c.get("pwf") == _password_fingerprint(account))


class ForgotPasswordBody(BaseModel):
    email: str = Field(max_length=254)
    role: Optional[Literal["user", "driver", "admin"]] = "user"


GENERIC_FORGOT_MESSAGE = "If an account exists for that email, password reset instructions have been sent."


@router.post("/forgot-password", summary="Start a password reset", dependencies=[Depends(ratelimit.limited("password_reset"))])
async def forgot_password(body: ForgotPasswordBody):
    """Issues a short-lived, single-use reset token. There is no e-mail delivery yet, so
    in development/test the token is returned in the response (it must never be returned
    in production, where it would let anyone who knows an address take the account over).
    In production the response is identical whether or not the account exists."""
    role = body.role or "user"
    Model = _model_for(role)
    account = await Model.find_one(Model.email == body.email.lower())

    if config.is_production():
        if account:
            log.warning("password reset requested but e-mail delivery is not configured",
                        extra={"event": "reset_requested", "role": role, "user_id": str(account.id)})
        return {"message": GENERIC_FORGOT_MESSAGE}

    if not account:
        raise HTTPException(status_code=404, detail="No account found with this email for the selected role.")
    return {"message": "Account verified. You can now set a new password.", "resetToken": make_reset_token(account, role)}


class ResetPasswordBody(BaseModel):
    email: str = Field(max_length=254)
    role: Optional[Literal["user", "driver", "admin"]] = "user"
    newPassword: Password
    resetToken: Optional[str] = Field(default=None, max_length=2000)


@router.post("/reset-password", summary="Reset password with a reset token", dependencies=[Depends(ratelimit.limited("password_reset"))])
async def reset_password(body: ResetPasswordBody):
    role = body.role or "user"
    Model = _model_for(role)
    account = await Model.find_one(Model.email == body.email.lower())
    if not account or not _check_reset_token(body.resetToken, account, role):
        log.warning("password reset rejected", extra={"event": "reset_rejected", "role": role})
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired. Request a new one.")
    account.password = hash_password(body.newPassword)
    await account.save()
    log.info("password reset", extra={"event": "reset_ok", "role": role, "user_id": str(account.id)})
    return {"message": "Password reset successfully. You can now log in."}


class ChangePasswordBody(BaseModel):
    currentPassword: str = Field(max_length=200)
    newPassword: Password


@router.post("/change-password", summary="Change password (requires current password)")
async def change_password(body: ChangePasswordBody, current_user: dict = Depends(get_current_user)):
    Model = _model_for(current_user["role"])
    account = await Model.get(PydanticObjectId(current_user["id"]))
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")
    if not account.compare_password(body.currentPassword):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    account.password = hash_password(body.newPassword)
    await account.save()
    return {"message": "Password changed successfully."}
