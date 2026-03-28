from pydantic import BaseModel, EmailStr, Field
from datetime import datetime


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


class BookPublic(BaseModel):
    id: int
    title: str
    author: str
    isbn: str
    description: str | None = None
    total_copies: int
    available_copies: int
    is_available: bool

    model_config = {"from_attributes": True}


class BorrowRequestCreate(BaseModel):
    book_id: int


class BorrowRequestPublic(BaseModel):
    id: int
    student_id: int
    book_id: int
    status: str
    requested_at: datetime
    approved_at: datetime | None = None
    denial_reason: str | None = None

    model_config = {"from_attributes": True}


class BorrowRecordPublic(BaseModel):
    id: int
    student_id: int
    book_id: int
    borrowed_at: datetime
    due_date: datetime
    returned_at: datetime | None = None
    is_returned: bool

    model_config = {"from_attributes": True}


class BorrowRecordWithBook(BaseModel):
    id: int
    book_id: int
    borrowed_at: datetime
    due_date: datetime
    returned_at: datetime | None = None
    is_returned: bool
    book: BookPublic

    model_config = {"from_attributes": True}


class FinePublic(BaseModel):
    id: int
    student_id: int
    borrow_record_id: int | None = None
    amount: float
    is_paid: bool
    reason: str
    created_at: datetime
    paid_at: datetime | None = None

    model_config = {"from_attributes": True}


class ReturnBookRequest(BaseModel):
    borrow_record_id: int


class MessageResponse(BaseModel):
    message: str
