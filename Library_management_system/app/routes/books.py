from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Book, BorrowRequest, BorrowRecord, Fine, Student, BorrowRequestStatus
from app.schemas import (
    BookPublic,
    BorrowRequestCreate,
    BorrowRequestPublic,
    BorrowRecordPublic,
    BorrowRecordWithBook,
    FinePublic,
    ReturnBookRequest,
    MessageResponse,
)
from app.security import decode_token

router = APIRouter(prefix="/books", tags=["Books"])
security = HTTPBearer()

BORROW_PERIOD_DAYS = 14


def get_current_student(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)) -> Student:
    """Verify token and extract current student."""
    try:
        token_payload = decode_token(credentials.credentials)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    student_id = token_payload.get("sub")
    if not student_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    student = db.query(Student).filter(Student.id == int(student_id)).first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found",
        )

    return student


@router.get("", response_model=list[BookPublic])
def list_available_books(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    search: str = Query("", min_length=0),
    db: Session = Depends(get_db)
):
    """List all available books with optional search by title or author."""
    query = db.query(Book).filter(Book.is_available == True)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Book.title.ilike(search_term)) |
            (Book.author.ilike(search_term))
        )

    books = query.offset(skip).limit(limit).all()
    return books


@router.get("/{book_id}", response_model=BookPublic)
def get_book_details(book_id: int, db: Session = Depends(get_db)):
    """Get detailed information about a specific book."""
    book = db.query(Book).filter(Book.id == book_id).first()

    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )

    return book


@router.post("/borrow", response_model=BorrowRequestPublic)
def request_borrow_book(
    payload: BorrowRequestCreate,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    """Student requests to borrow a book."""
    book = db.query(Book).filter(Book.id == payload.book_id).first()

    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )

    if not book.is_available or book.available_copies <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Book is not available for borrowing",
        )

    # Check if student already has a pending request for this book
    existing_request = db.query(BorrowRequest).filter(
        BorrowRequest.student_id == current_student.id,
        BorrowRequest.book_id == payload.book_id,
        BorrowRequest.status == BorrowRequestStatus.PENDING
    ).first()

    if existing_request:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You already have a pending request for this book",
        )

    borrow_request = BorrowRequest(
        student_id=current_student.id,
        book_id=payload.book_id,
        status=BorrowRequestStatus.PENDING,
    )
    db.add(borrow_request)
    db.commit()
    db.refresh(borrow_request)

    return borrow_request


@router.get("/my-borrowed-books", response_model=list[BorrowRecordWithBook])
def get_borrowed_books(
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    """Get all currently borrowed books (not yet returned)."""
    records = db.query(BorrowRecord).filter(
        BorrowRecord.student_id == current_student.id,
        BorrowRecord.is_returned == False
    ).all()

    # Eager load book details
    result = []
    for record in records:
        book = db.query(Book).filter(Book.id == record.book_id).first()
        result.append({
            "id": record.id,
            "book_id": record.book_id,
            "borrowed_at": record.borrowed_at,
            "due_date": record.due_date,
            "returned_at": record.returned_at,
            "is_returned": record.is_returned,
            "book": book,
        })

    return result


@router.get("/my-borrowing-history", response_model=list[BorrowRecordWithBook])
def get_borrowing_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    """Get all past borrowing records (returned books)."""
    records = db.query(BorrowRecord).filter(
        BorrowRecord.student_id == current_student.id,
        BorrowRecord.is_returned == True
    ).order_by(BorrowRecord.returned_at.desc()).offset(skip).limit(limit).all()

    # Eager load book details
    result = []
    for record in records:
        book = db.query(Book).filter(Book.id == record.book_id).first()
        result.append({
            "id": record.id,
            "book_id": record.book_id,
            "borrowed_at": record.borrowed_at,
            "due_date": record.due_date,
            "returned_at": record.returned_at,
            "is_returned": record.is_returned,
            "book": book,
        })

    return result


@router.post("/return", response_model=MessageResponse)
def return_book(
    payload: ReturnBookRequest,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    """Student returns a borrowed book."""
    record = db.query(BorrowRecord).filter(
        BorrowRecord.id == payload.borrow_record_id,
        BorrowRecord.student_id == current_student.id
    ).first()

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Borrow record not found",
        )

    if record.is_returned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This book has already been returned",
        )

    # Update borrow record
    record.returned_at = datetime.now(timezone.utc)
    record.is_returned = True

    # Increase available copies
    book = db.query(Book).filter(Book.id == record.book_id).first()
    book.available_copies += 1
    if book.available_copies > 0:
        book.is_available = True

    # Check for late return and create fine if needed
    if datetime.now(timezone.utc) > record.due_date:
        days_late = (datetime.now(timezone.utc) - record.due_date).days
        fine_amount = days_late * 10  # 10 units per day late
        fine = Fine(
            student_id=current_student.id,
            borrow_record_id=record.id,
            amount=fine_amount,
            reason=f"Late return ({days_late} days overdue)",
            is_paid=False,
        )
        db.add(fine)

    db.commit()

    return {"message": "Book returned successfully"}


@router.get("/my-fines", response_model=list[FinePublic])
def get_student_fines(
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    """Get all outstanding and paid fines for the student."""
    fines = db.query(Fine).filter(
        Fine.student_id == current_student.id
    ).order_by(Fine.created_at.desc()).all()

    return fines


@router.get("/my-fines/outstanding", response_model=list[FinePublic])
def get_outstanding_fines(
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    """Get only outstanding (unpaid) fines."""
    fines = db.query(Fine).filter(
        Fine.student_id == current_student.id,
        Fine.is_paid == False
    ).all()

    return fines
