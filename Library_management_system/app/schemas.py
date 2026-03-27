from pydantic import BaseModel, EmailStr, Field


class StudentRegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    registration_number: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)


class StudentLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class StudentPublic(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    registration_number: str
    is_active: bool

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    student: StudentPublic
