from pydantic import BaseModel, EmailStr, Field


class StudentRegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    registration_number: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)


class StudentLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10)
    new_password: str = Field(min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class StudentPublic(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    registration_number: str
    is_active: bool

    model_config = {"from_attributes": True}


class LibrarianPublic(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    is_active: bool
    is_admin: bool

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_type: str
    student: StudentPublic | None = None
    librarian: LibrarianPublic | None = None


class RegisterResponse(BaseModel):
    message: str
