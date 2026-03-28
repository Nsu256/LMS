from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.database import get_db
from app.models import Book, BorrowRequest, BorrowRecord, Fine, Student, Librarian, BorrowRequestStatus
from app.schemas import (
    BookPublic,
    BookCreate,
    BookUpdate,
    DenyBorrowRequest,
    FineCreate,
    BorrowRequestWithStudentBook,
    BorrowRecordWithStudentBook,
    StudentWithFines,
    BorrowingReport,
    StudentFineClearanceResponse,
    MessageResponse,
)
from app.security import decode_token

router = APIRouter(prefix="/admin", tags=["Admin"])
security = HTTPBearer()


def get_current_librarian(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)) -> Librarian:
    """Verify token and extract current librarian with admin privileges."""
    try:
        token_payload = decode_token(credentials.credentials)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    librarian_id = token_payload.get("sub")
    if not librarian_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    librarian = db.query(Librarian).filter(Librarian.id == int(librarian_id)).first()
    if not librarian:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Librarian not found",
        )

    if not librarian.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can access this endpoint",
        )

    return librarian


# ==================== BOOK MANAGEMENT ====================

@router.post("/books", response_model=BookPublic, status_code=status.HTTP_201_CREATED)
def add_book_to_catalog(
    payload: BookCreate,
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """Add a new book to the catalog."""
    # Check if book with same ISBN already exists
    existing_book = db.query(Book).filter(Book.isbn == payload.isbn).first()
    if existing_book:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Book with this ISBN already exists",
        )

    book = Book(
        title=payload.title,
        author=payload.author,
        isbn=payload.isbn,
        description=payload.description,
        total_copies=payload.total_copies,
        available_copies=payload.total_copies,
        is_available=True,
    )
    db.add(book)
    db.commit()
    db.refresh(book)

    return book


@router.put("/books/{book_id}", response_model=BookPublic)
def edit_book_details(
    book_id: int,
    payload: BookUpdate,
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """Edit book details."""
    book = db.query(Book).filter(Book.id == book_id).first()

    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )

    # Check ISBN uniqueness if changing ISBN
    if payload.isbn and payload.isbn != book.isbn:
        existing = db.query(Book).filter(Book.isbn == payload.isbn).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Another book with this ISBN already exists",
            )

    # Update fields only if provided
    if payload.title:
        book.title = payload.title
    if payload.author:
        book.author = payload.author
    if payload.isbn:
        book.isbn = payload.isbn
    if payload.description is not None:
        book.description = payload.description
    if payload.total_copies:
        # Adjust available copies if total changed
        diff = payload.total_copies - book.total_copies
        book.total_copies = payload.total_copies
        book.available_copies = min(book.available_copies + diff, payload.total_copies)

    # Update is_available based on available_copies
    book.is_available = book.available_copies > 0

    db.commit()
    db.refresh(book)

    return book


@router.delete("/books/{book_id}", response_model=MessageResponse)
def remove_book_from_catalog(
    book_id: int,
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """Remove book from catalog."""
    book = db.query(Book).filter(Book.id == book_id).first()

    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )

    # Check if book is currently borrowed
    active_borrows = db.query(BorrowRecord).filter(
        BorrowRecord.book_id == book_id,
        BorrowRecord.is_returned == False
    ).count()

    if active_borrows > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete book that is currently borrowed. All copies must be returned first.",
        )

    db.delete(book)
    db.commit()

    return {"message": "Book removed from catalog"}


# ==================== STUDENT MANAGEMENT ====================

@router.get("/students", response_model=list[StudentWithFines])
def list_all_students(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """List all students with their outstanding fines."""
    students = db.query(Student).offset(skip).limit(limit).all()

    result = []
    for student in students:
        outstanding_fines = db.query(func.sum(Fine.amount)).filter(
            Fine.student_id == student.id,
            Fine.is_paid == False
        ).scalar() or 0.0

        result.append({
            "id": student.id,
            "full_name": student.full_name,
            "email": student.email,
            "registration_number": student.registration_number,
            "is_active": student.is_active,
            "outstanding_fines": outstanding_fines,
        })

    return result


@router.post("/students/{student_id}/clear", response_model=StudentFineClearanceResponse)
def clear_student_fines(
    student_id: int,
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """Clear all outstanding fines for a student after physical payment confirmation."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found",
        )

    unpaid_fines = db.query(Fine).filter(
        Fine.student_id == student_id,
        Fine.is_paid == False,
    ).all()

    if not unpaid_fines:
        return StudentFineClearanceResponse(
            message="Student has no outstanding fines",
            student_id=student_id,
            cleared_fines_count=0,
            total_cleared_amount=0.0,
        )

    now = datetime.now(timezone.utc)
    total_cleared_amount = 0.0
    for fine in unpaid_fines:
        total_cleared_amount += float(fine.amount)
        fine.is_paid = True
        fine.paid_at = now

    db.commit()

    return StudentFineClearanceResponse(
        message="Student fines cleared successfully",
        student_id=student_id,
        cleared_fines_count=len(unpaid_fines),
        total_cleared_amount=total_cleared_amount,
    )


# ==================== BORROW REQUEST MANAGEMENT ====================

@router.get("/borrow-requests", response_model=list[BorrowRequestWithStudentBook])
def view_pending_borrow_requests(
    status_filter: str = Query("pending", regex="^(pending|approved|denied|cancelled)$"),
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """View borrow requests filtered by status."""
    # Convert string to enum
    status_enum = BorrowRequestStatus[status_filter.upper()]

    requests = db.query(BorrowRequest).filter(
        BorrowRequest.status == status_enum
    ).order_by(BorrowRequest.requested_at.desc()).all()

    result = []
    for req in requests:
        student = db.query(Student).filter(Student.id == req.student_id).first()
        book = db.query(Book).filter(Book.id == req.book_id).first()
        result.append({
            "id": req.id,
            "student_id": req.student_id,
            "book_id": req.book_id,
            "status": req.status.value,
            "requested_at": req.requested_at,
            "approved_at": req.approved_at,
            "denial_reason": req.denial_reason,
            "student": student,
            "book": book,
        })

    return result


@router.post("/borrow-requests/{request_id}/approve", response_model=MessageResponse)
def approve_borrow_request(
    request_id: int,
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """Approve a borrow request and create active borrow record."""
    borrow_request = db.query(BorrowRequest).filter(BorrowRequest.id == request_id).first()

    if not borrow_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Borrow request not found",
        )

    if borrow_request.status != BorrowRequestStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Request is already {borrow_request.status.value}",
        )

    book = db.query(Book).filter(Book.id == borrow_request.book_id).first()

    if not book or book.available_copies <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Book is no longer available",
        )

    # Update request status
    borrow_request.status = BorrowRequestStatus.APPROVED
    borrow_request.approved_at = datetime.now(timezone.utc)

    # Create borrow record
    from datetime import timedelta
    due_date = datetime.now(timezone.utc) + timedelta(days=14)
    borrow_record = BorrowRecord(
        student_id=borrow_request.student_id,
        book_id=borrow_request.book_id,
        due_date=due_date,
        is_returned=False,
    )

    # Decrease available copies
    book.available_copies -= 1
    book.is_available = book.available_copies > 0

    db.add(borrow_record)
    db.commit()

    return {"message": "Borrow request approved"}


@router.post("/borrow-requests/{request_id}/deny", response_model=MessageResponse)
def deny_borrow_request(
    request_id: int,
    payload: DenyBorrowRequest,
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """Deny a borrow request."""
    borrow_request = db.query(BorrowRequest).filter(BorrowRequest.id == request_id).first()

    if not borrow_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Borrow request not found",
        )

    if borrow_request.status != BorrowRequestStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Request is already {borrow_request.status.value}",
        )

    borrow_request.status = BorrowRequestStatus.DENIED
    borrow_request.denial_reason = payload.denial_reason
    borrow_request.approved_at = datetime.now(timezone.utc)

    db.commit()

    return {"message": "Borrow request denied"}


# ==================== OVERDUE MANAGEMENT ====================

@router.get("/overdue-books", response_model=list[BorrowRecordWithStudentBook])
def view_overdue_books(
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """View books not returned on time."""
    now = datetime.now(timezone.utc)
    overdue_records = db.query(BorrowRecord).filter(
        BorrowRecord.is_returned == False,
        BorrowRecord.due_date < now
    ).order_by(BorrowRecord.due_date.asc()).all()

    result = []
    for record in overdue_records:
        student = db.query(Student).filter(Student.id == record.student_id).first()
        book = db.query(Book).filter(Book.id == record.book_id).first()
        result.append({
            "id": record.id,
            "student_id": record.student_id,
            "book_id": record.book_id,
            "borrowed_at": record.borrowed_at,
            "due_date": record.due_date,
            "returned_at": record.returned_at,
            "is_returned": record.is_returned,
            "student": student,
            "book": book,
        })

    return result


# ==================== FINE MANAGEMENT ====================

@router.post("/fines/{student_id}", response_model=FinePublic)
def assign_fine_to_student(
    student_id: int,
    payload: FineCreate,
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """Assign or update a fine for a student."""
    student = db.query(Student).filter(Student.id == student_id).first()

    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found",
        )

    fine = Fine(
        student_id=student_id,
        amount=payload.amount,
        reason=payload.reason,
        is_paid=False,
    )

    db.add(fine)
    db.commit()
    db.refresh(fine)

    return fine


# ==================== REPORTS ====================

@router.get("/reports", response_model=BorrowingReport)
def generate_borrowing_report(
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """Generate borrowing and returns report."""
    total_books = db.query(func.count(Book.id)).scalar() or 0
    total_available = db.query(func.sum(Book.available_copies)).scalar() or 0
    total_borrowed = total_books - total_available if total_books > 0 else 0

    pending_requests = db.query(func.count(BorrowRequest.id)).filter(
        BorrowRequest.status == BorrowRequestStatus.PENDING
    ).scalar() or 0

    active_borrows = db.query(func.count(BorrowRecord.id)).filter(
        BorrowRecord.is_returned == False
    ).scalar() or 0

    now = datetime.now(timezone.utc)
    overdue_books = db.query(func.count(BorrowRecord.id)).filter(
        BorrowRecord.is_returned == False,
        BorrowRecord.due_date < now
    ).scalar() or 0

    active_students = db.query(func.count(Student.id)).filter(
        Student.is_active == True
    ).scalar() or 0

    outstanding_fines = db.query(func.sum(Fine.amount)).filter(
        Fine.is_paid == False
    ).scalar() or 0.0

    return {
        "total_books_in_catalog": total_books,
        "total_available_copies": total_available,
        "total_borrowed_copies": total_borrowed,
        "total_pending_requests": pending_requests,
        "total_active_borrows": active_borrows,
        "total_overdue_books": overdue_books,
        "total_active_students": active_students,
        "total_outstanding_fines": outstanding_fines,
    }
