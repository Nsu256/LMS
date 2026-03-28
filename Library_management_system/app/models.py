from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column
import enum

from app.database import Base


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    full_name: Mapped[str] = mapped_column(String(120), nullable=False)

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)

    registration_number: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)

    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class Librarian(Base):
    __tablename__ = "librarians"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    full_name: Mapped[str] = mapped_column(String(120), nullable=False)

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)

    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    is_admin: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    author: Mapped[str] = mapped_column(String(255), nullable=False)

    isbn: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)

    description: Mapped[str] = mapped_column(String(1000), nullable=True)

    publication_year: Mapped[int] = mapped_column(Integer, nullable=True, index=True)

    total_copies: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    available_copies: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    is_available: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    name: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)

    description: Mapped[str] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class BookCategory(Base):
    __tablename__ = "book_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("books.id"), nullable=False, index=True)

    category_id: Mapped[int] = mapped_column(Integer, ForeignKey("categories.id"), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class BookCondition(enum.Enum):
    GOOD = "good"
    FAIR = "fair"
    DAMAGED = "damaged"


class BookConditionStatus(Base):
    __tablename__ = "book_condition_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("books.id"), unique=True, nullable=False)

    condition: Mapped[str] = mapped_column(Enum(BookCondition), nullable=False)

    updated_by_librarian_id: Mapped[int] = mapped_column(Integer, ForeignKey("librarians.id"), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class BorrowRequestStatus(enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    CANCELLED = "cancelled"


class BorrowRequest(Base):
    __tablename__ = "borrow_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), nullable=False)

    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("books.id"), nullable=False)

    status: Mapped[str] = mapped_column(Enum(BorrowRequestStatus), default=BorrowRequestStatus.PENDING)

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    denial_reason: Mapped[str] = mapped_column(String(500), nullable=True)


class BorrowRecord(Base):
    __tablename__ = "borrow_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), nullable=False)

    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("books.id"), nullable=False)

    borrowed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    returned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    is_returned: Mapped[bool] = mapped_column(Boolean, default=False)


class Fine(Base):
    __tablename__ = "fines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), nullable=False)

    borrow_record_id: Mapped[int] = mapped_column(Integer, ForeignKey("borrow_records.id"), nullable=True)

    amount: Mapped[float] = mapped_column(Integer, nullable=False)

    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)

    reason: Mapped[str] = mapped_column(String(255), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


class NotificationType(enum.Enum):
    DUE_REMINDER = "due_reminder"
    OVERDUE_ALERT = "overdue_alert"
    FINE_NOTICE = "fine_notice"


class NotificationStatus(enum.Enum):
    SENT = "sent"
    FAILED = "failed"


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), nullable=True)

    sent_by_librarian_id: Mapped[int] = mapped_column(Integer, ForeignKey("librarians.id"), nullable=True)

    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    subject: Mapped[str] = mapped_column(String(255), nullable=False)

    body: Mapped[str] = mapped_column(String(2000), nullable=False)

    notification_type: Mapped[str] = mapped_column(Enum(NotificationType), nullable=False)

    status: Mapped[str] = mapped_column(Enum(NotificationStatus), nullable=False)

    error_message: Mapped[str] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
