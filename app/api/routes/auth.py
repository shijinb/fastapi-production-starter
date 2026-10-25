from fastapi import APIRouter, status

from app.api.deps import CurrentUser, SessionDep, SettingsDep
from app.models import Organization
from app.schemas import LoginRequest, MeResponse, OrganizationRead, RefreshRequest, RegisterRequest, TokenResponse
from app.services import auth

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Create an organization and its owner account",
    responses={409: {"description": "E-mail already registered"}},
)
async def register(data: RegisterRequest, session: SessionDep, settings: SettingsDep) -> TokenResponse:
    user = await auth.register(session, data)
    return await auth.login(session, settings, user.email, data.password)


@router.post("/login", summary="Exchange e-mail and password for tokens", responses={401: {"description": "Bad credentials"}})
async def login(data: LoginRequest, session: SessionDep, settings: SettingsDep) -> TokenResponse:
    return await auth.login(session, settings, data.email, data.password)


@router.post(
    "/refresh",
    summary="Rotate a refresh token",
    description="Returns a new access token and a new refresh token. The old refresh token stops working; "
    "presenting it again revokes the whole session.",
    responses={401: {"description": "Invalid, expired or reused refresh token"}},
)
async def refresh(data: RefreshRequest, session: SessionDep, settings: SettingsDep) -> TokenResponse:
    return await auth.refresh(session, settings, data.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke the session of a refresh token")
async def logout(data: RefreshRequest, session: SessionDep, settings: SettingsDep) -> None:
    await auth.logout(session, settings, data.refresh_token)


@router.get("/me", summary="The authenticated user and organization")
async def me(user: CurrentUser, session: SessionDep) -> MeResponse:
    organization = await session.get(Organization, user.organization_id)
    return MeResponse.model_validate(user, from_attributes=True).model_copy(
        update={"organization": OrganizationRead.model_validate(organization)}
    )
