from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.audit import log_audit_event
from app.models import Book, BookCategory, BorrowRequest, BorrowRecord, Category, Fine, Student, BorrowRequestStatus
from app.schemas import (
    BookPublic,
    CategoryPublic,
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
security = HTTPBearer(auto_error=False)
BOOK_FILES_DIR = Path(__file__).resolve().parents[2] / "storage" / "book_files"

BORROW_PERIOD_DAYS = 14


def _get_book_file_path(book_id: int) -> Path | None:
    if not BOOK_FILES_DIR.exists():
        return None

    for file_path in BOOK_FILES_DIR.glob(f"{book_id}.*"):
        if file_path.is_file():
            return file_path
    return None


def _build_category_map(book_ids: list[int], db: Session) -> dict[int, tuple[int | None, str | None]]:
    if not book_ids:
        return {}

    rows = (
        db.query(BookCategory.book_id, Category.id, Category.name)
        .join(Category, Category.id == BookCategory.category_id)
        .filter(BookCategory.book_id.in_(book_ids))
        .all()
    )
    return {int(book_id): (int(category_id), category_name) for book_id, category_id, category_name in rows}


def _book_to_public(book: Book, category_map: dict[int, tuple[int | None, str | None]]) -> dict:
    category_id, category_name = category_map.get(book.id, (None, None))
    return {
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "isbn": book.isbn,
        "description": book.description,
        "publication_year": book.publication_year,
        "total_copies": book.total_copies,
        "available_copies": book.available_copies,
        "is_available": book.is_available,
        "category_id": category_id,
        "category_name": category_name,
    }


def get_current_student(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> Student:
    """Authentication checks are bypassed for student endpoints."""
    # try:
    #     token_payload = decode_token(credentials.credentials)
    # except ValueError:
    #     raise HTTPException(
    #         status_code=status.HTTP_401_UNAUTHORIZED,
    #         detail="Invalid token",
    #     )
    #
    # student_id = token_payload.get("sub")
    # if not student_id:
    #     raise HTTPException(
    #         status_code=status.HTTP_401_UNAUTHORIZED,
    #         detail="Invalid token",
    #     )
    #
    # student = db.query(Student).filter(Student.id == int(student_id)).first()
    # if not student:
    #     raise HTTPException(
    #         status_code=status.HTTP_404_NOT_FOUND,
    #         detail="Student not found",
    #     )

    student = db.query(Student).first()
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
    category_map = _build_category_map([book.id for book in books], db)
    return [_book_to_public(book, category_map) for book in books]


@router.get("/categories", response_model=list[CategoryPublic])
def list_book_categories(db: Session = Depends(get_db)):
    categories = db.query(Category).order_by(Category.name.asc()).all()
    return categories


@router.get("/search", response_model=list[BookPublic])
def advanced_search_books(
    title: str = Query("", min_length=0),
    author: str = Query("", min_length=0),
    isbn: str = Query("", min_length=0),
    category: str = Query("", min_length=0),
    year_from: int | None = Query(None, ge=1000, le=2100),
    year_to: int | None = Query(None, ge=1000, le=2100),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(Book)

    if title:
        query = query.filter(Book.title.ilike(f"%{title}%"))
    if author:
        query = query.filter(Book.author.ilike(f"%{author}%"))
    if isbn:
        query = query.filter(Book.isbn.ilike(f"%{isbn}%"))
    if year_from is not None:
        query = query.filter(Book.publication_year >= year_from)
    if year_to is not None:
        query = query.filter(Book.publication_year <= year_to)

    if category:
        query = (
            query.join(BookCategory, BookCategory.book_id == Book.id)
            .join(Category, Category.id == BookCategory.category_id)
            .filter(Category.name.ilike(f"%{category}%"))
        )

    books = query.order_by(Book.title.asc()).offset(skip).limit(limit).all()
    category_map = _build_category_map([book.id for book in books], db)
    return [_book_to_public(book, category_map) for book in books]


@router.get("/search/suggestions", response_model=list[str])
def search_suggestions(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(10, ge=1, le=20),
    db: Session = Depends(get_db),
):
    pattern = f"%{q}%"

    book_rows = (
        db.query(Book.title, Book.author)
        .filter(
            or_(
                Book.title.ilike(pattern),
                Book.author.ilike(pattern),
                Book.isbn.ilike(pattern),
            )
        )
        .order_by(Book.title.asc())
        .limit(limit)
        .all()
    )

    category_rows = (
        db.query(Category.name)
        .filter(Category.name.ilike(pattern))
        .order_by(Category.name.asc())
        .limit(limit)
        .all()
    )

    suggestions: list[str] = []
    for title_value, author_value in book_rows:
        if title_value and title_value not in suggestions:
            suggestions.append(title_value)
        if author_value and author_value not in suggestions:
            suggestions.append(author_value)

    for (category_name,) in category_rows:
        if category_name and category_name not in suggestions:
            suggestions.append(category_name)

    return suggestions[:limit]


@router.get("/category/{category_id}", response_model=list[BookPublic])
def list_books_by_category(
    category_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    books = (
        db.query(Book)
        .join(BookCategory, BookCategory.book_id == Book.id)
        .filter(BookCategory.category_id == category_id)
        .order_by(Book.title.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    category_map = _build_category_map([book.id for book in books], db)
    return [_book_to_public(book, category_map) for book in books]


@router.get("/{book_id}/download")
def download_book_file(
    book_id: int,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """Download the uploaded digital file for a book."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )

    file_path = _get_book_file_path(book_id)
    if not file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No digital file is available for this book",
        )

    media_types = {
        ".pdf": "application/pdf",
        ".epub": "application/epub+zip",
        ".txt": "text/plain",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".csv": "text/csv",
    }
    suffix = file_path.suffix.lower()
    media_type = media_types.get(suffix, "application/octet-stream")
    download_name = f"{book.title}{suffix}".replace("/", "-")

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=download_name,
    )


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
    db.flush()

    log_audit_event(
        db,
        action="borrow_requested",
        actor_type="student",
        user_id=current_student.id,
        resource="borrow_request",
        resource_id=borrow_request.id,
        details=f"Requested borrow for book_id={payload.book_id}",
    )

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
        if not book:
            continue
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
        if not book:
            continue
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
    now_utc = datetime.now(timezone.utc)
    record.returned_at = now_utc
    record.is_returned = True

    # Increase available copies
    book = db.query(Book).filter(Book.id == record.book_id).first()
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )
    book.available_copies += 1
    if book.available_copies > 0:
        book.is_available = True

    # Check for late return and create fine if needed
    due_date = record.due_date
    if due_date.tzinfo is None:
        due_date = due_date.replace(tzinfo=timezone.utc)

    if now_utc > due_date:
        days_late = (now_utc - due_date).days
        fine_amount = days_late * 10  # 10 units per day late
        fine = Fine(
            student_id=current_student.id,
            borrow_record_id=record.id,
            amount=fine_amount,
            reason=f"Late return ({days_late} days overdue)",
            is_paid=False,
        )
        db.add(fine)

    log_audit_event(
        db,
        action="book_returned",
        actor_type="student",
        user_id=current_student.id,
        resource="borrow_record",
        resource_id=record.id,
        details=f"Returned book_id={record.book_id}",
    )

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


@router.get("/{book_id}", response_model=BookPublic)
def get_book_details(book_id: int, db: Session = Depends(get_db)):
    """Get detailed information about a specific book."""
    book = db.query(Book).filter(Book.id == book_id).first()

    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )

    category_map = _build_category_map([book.id], db)
    return _book_to_public(book, category_map)
