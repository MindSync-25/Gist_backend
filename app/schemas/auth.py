from datetime import datetime

from pydantic import BaseModel, Field


class AuthUserOut(BaseModel):
    id: int
    username: str
    email: str
    display_name: str
    bio: str | None = None
    location: str | None = None
    avatar_url: str | None = None
    avatar_display_url: str | None = None
    avatar_display_expires_at: datetime | None = None

    model_config = {"from_attributes": True}


class SignUpIn(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=2, max_length=80)


class SignInIn(BaseModel):
    login: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=20)


class LogoutIn(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=20)


class ProfileUpdateIn(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=50)
    email: str | None = Field(default=None, min_length=5, max_length=255)
    display_name: str | None = Field(default=None, min_length=2, max_length=80)
    bio: str | None = Field(default=None, max_length=280)
    location: str | None = Field(default=None, max_length=120)
    avatar_url: str | None = Field(default=None, max_length=2048)


class LogoutOut(BaseModel):
    success: bool = True


class AuthTokenOut(BaseModel):
    access_token: str
    refresh_token: str
    access_expires_in_seconds: int
    refresh_expires_in_seconds: int
    token_type: str = "bearer"
    user: AuthUserOut
