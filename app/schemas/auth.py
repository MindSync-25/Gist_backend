from datetime import date, datetime

from pydantic import BaseModel, Field


class AuthUserOut(BaseModel):
    id: int
    username: str
    email: str
    display_name: str
    date_of_birth: date | None = None
    bio: str | None = None
    location: str | None = None
    avatar_url: str | None = None
    language: str | None = "en"
    avatar_display_url: str | None = None
    avatar_display_expires_at: datetime | None = None
    google_connected: bool = False
    apple_connected: bool = False
    preferred_topic_slugs: list[str] = []
    preferred_languages: list[str] = ["en"]
    onboarding_completed: bool = False

    model_config = {"from_attributes": True}


class SignUpIn(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=2, max_length=80)
    date_of_birth: date


class SignUpRequestOtpIn(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=2, max_length=80)
    date_of_birth: date


class SignUpVerifyOtpIn(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    otp: str = Field(min_length=6, max_length=6)


class OtpAckOut(BaseModel):
    success: bool = True
    message: str


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
    date_of_birth: date | None = None
    bio: str | None = Field(default=None, max_length=280)
    location: str | None = Field(default=None, max_length=120)
    avatar_url: str | None = Field(default=None, max_length=2048)
    language: str | None = Field(default=None, max_length=10)


class LogoutOut(BaseModel):
    success: bool = True


class AuthTokenOut(BaseModel):
    access_token: str
    refresh_token: str
    access_expires_in_seconds: int
    refresh_expires_in_seconds: int
    token_type: str = "bearer"
    user: AuthUserOut


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class ForgotPasswordRequestOtpIn(BaseModel):
    email: str = Field(min_length=5, max_length=255)


class ForgotPasswordResetIn(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    otp: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8, max_length=128)


class SocialSignInIn(BaseModel):
    provider: str = Field(pattern="^(google|apple)$")
    # id_token flow (iOS, Apple, existing flows)
    id_token: str | None = Field(default=None, min_length=20)
    # Google Android authorization code flow
    code: str | None = Field(default=None, min_length=10)
    redirect_uri: str | None = Field(default=None)
    code_verifier: str | None = Field(default=None)
    email: str | None = Field(default=None, min_length=5, max_length=255)
    display_name: str | None = Field(default=None, min_length=2, max_length=80)


class SocialConnectIn(BaseModel):
    provider: str = Field(pattern="^(google|apple)$")
    id_token: str = Field(min_length=20)
    email: str | None = Field(default=None, min_length=5, max_length=255)
