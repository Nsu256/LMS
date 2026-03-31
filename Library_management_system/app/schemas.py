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
    publication_year: int | None = None
    total_copies: int
    available_copies: int
    is_available: bool
    category_id: int | None = None
    category_name: str | None = None

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


class BookCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    author: str = Field(min_length=1, max_length=255)
    isbn: str = Field(min_length=5, max_length=20)
    description: str | None = Field(None, max_length=1000)
    publication_year: int | None = Field(None, ge=1000, le=2100)
    total_copies: int = Field(ge=1)
    category_id: int | None = None


class BookUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    author: str | None = Field(None, min_length=1, max_length=255)
    isbn: str | None = Field(None, min_length=5, max_length=20)
    description: str | None = Field(None, max_length=1000)
    publication_year: int | None = Field(None, ge=1000, le=2100)
    total_copies: int | None = Field(None, ge=1)
    category_id: int | None = None


class CategoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(None, max_length=500)


class CategoryPublic(BaseModel):
    id: int
    name: str
    description: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class BookConditionUpdateRequest(BaseModel):
    condition: str = Field(pattern="^(good|fair|damaged)$")


class BookConditionUpdateResponse(BaseModel):
    message: str
    book_id: int
    condition: str
    updated_at: datetime


class DenyBorrowRequest(BaseModel):
    denial_reason: str = Field(min_length=5, max_length=500)


class FineCreate(BaseModel):
    amount: float = Field(ge=0)
    reason: str = Field(min_length=5, max_length=255)


class BorrowRequestWithStudentBook(BaseModel):
    id: int
    student_id: int
    book_id: int
    status: str
    requested_at: datetime
    approved_at: datetime | None = None
    denial_reason: str | None = None
    student: StudentPublic
    book: BookPublic

    model_config = {"from_attributes": True}


class BorrowRecordWithStudentBook(BaseModel):
    id: int
    student_id: int
    book_id: int
    borrowed_at: datetime
    due_date: datetime
    returned_at: datetime | None = None
    is_returned: bool
    student: StudentPublic
    book: BookPublic

    model_config = {"from_attributes": True}


class StudentWithFines(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    registration_number: str
    is_active: bool
    outstanding_fines: float = 0.0

    model_config = {"from_attributes": True}


class BorrowingReport(BaseModel):
    total_books_in_catalog: int
    total_available_copies: int
    total_borrowed_copies: int
    total_pending_requests: int
    total_active_borrows: int
    total_overdue_books: int
    total_active_students: int
    total_outstanding_fines: float


class StudentFineClearanceResponse(BaseModel):
    message: str
    student_id: int
    cleared_fines_count: int
    total_cleared_amount: float


class BookImportError(BaseModel):
    row: int
    error: str


class BookImportResponse(BaseModel):
    message: str
    total_rows: int
    imported_count: int
    skipped_count: int
    errors: list[BookImportError]


# ==================== STATISTICS SCHEMAS ====================

class TopBorrower(BaseModel):
    student_id: int
    full_name: str
    email: str
    borrow_count: int


class StudentStats(BaseModel):
    total_active_students: int
    top_borrowers: list[TopBorrower]
    defaulters_count: int
    compliance_rate: float


class MostBorrowedBook(BaseModel):
    book_id: int
    title: str
    author: str
    borrow_count: int
    availability_percentage: float


class BookInventoryStats(BaseModel):
    total_books: int
    total_copies: int
    available_copies: int
    borrowed_copies: int
    books_with_zero_availability: int


class BorrowingTrend(BaseModel):
    date: str
    borrow_count: int
    return_count: int
    new_requests: int


class BorrowingTrendsStats(BaseModel):
    average_borrow_duration_days: float
    on_time_return_rate: float
    late_return_rate: float
    trends: list[BorrowingTrend]


class FineStats(BaseModel):
    total_outstanding_fines: float
    total_collected_fines: float
    fine_count_unpaid: int
    fine_count_paid: int
    average_fine_amount: float


class TopDefaulter(BaseModel):
    student_id: int
    full_name: str
    email: str
    outstanding_amount: float
    overdue_books_count: int


class OverdueStats(BaseModel):
    total_overdue_books: int
    books_1_to_7_days_late: int
    books_8_to_14_days_late: int
    books_15_plus_days_late: int
    overdue_by_student: list[TopDefaulter]


class SystemHealthStats(BaseModel):
    pending_requests: int
    active_borrows: int
    average_approval_time_hours: float
    system_uptime: str


class DetailedReport(BaseModel):
    title: str
    generated_at: datetime
    total_records: int
    data: list[dict]


# ==================== NOTIFICATION SCHEMAS ====================

class SendNotificationEmailRequest(BaseModel):
    student_id: int
    notification_type: str = Field(pattern="^(due_reminder|overdue_alert|fine_notice)$")
    subject: str = Field(min_length=3, max_length=255)
    message: str = Field(min_length=3, max_length=2000)


class NotificationPublic(BaseModel):
    id: int
    student_id: int | None = None
    sent_by_librarian_id: int | None = None
    recipient_email: EmailStr
    subject: str
    body: str
    notification_type: str
    status: str
    error_message: str | None = None
    created_at: datetime
    sent_at: datetime | None = None

    model_config = {"from_attributes": True}


class NotificationSendResponse(BaseModel):
    message: str
    notification: NotificationPublic


class AuditLogPublic(BaseModel):
    id: int
    action: str
    actor_type: str
    user_id: int
    resource: str
    resource_id: int | None = None
    details: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
