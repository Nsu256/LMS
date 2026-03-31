import csv
from datetime import date, datetime, timezone
from io import BytesIO, StringIO
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from pydantic import ValidationError

from app.database import get_db
from app.models import (
    Book,
    BookCategory,
    BookCondition,
    BookConditionStatus,
    AuditLog,
    BorrowRequest,
    BorrowRecord,
    Category,
    Fine,
    Student,
    Librarian,
    BorrowRequestStatus,
)
from app.schemas import (
    AuditLogPublic,
    BookConditionUpdateRequest,
    BookConditionUpdateResponse,
    BookPublic,
    BookCreate,
    BookUpdate,
    CategoryCreate,
    CategoryPublic,
    DenyBorrowRequest,
    FineCreate,
    FinePublic,
    BorrowRequestWithStudentBook,
    BorrowRecordWithStudentBook,
    StudentWithFines,
    BorrowingReport,
    StudentFineClearanceResponse,
    MessageResponse,
    BookImportResponse,
)
from app.audit import log_audit_event
from app.security import decode_token

router = APIRouter(prefix="/admin", tags=["Admin"])
security = HTTPBearer(auto_error=False)
BOOK_FILES_DIR = Path(__file__).resolve().parents[2] / "storage" / "book_files"


def _book_to_public(book: Book, db: Session) -> dict:
    row = (
        db.query(Category.id, Category.name)
        .join(BookCategory, BookCategory.category_id == Category.id)
        .filter(BookCategory.book_id == book.id)
        .first()
    )
    category_id = int(row[0]) if row else None
    category_name = row[1] if row else None

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


def get_current_librarian(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> Librarian:
    """Authentication checks are bypassed for admin endpoints."""
    # try:
    #     token_payload = decode_token(credentials.credentials)
    # except ValueError:
    #     raise HTTPException(
    #         status_code=status.HTTP_401_UNAUTHORIZED,
    #         detail="Invalid token",
    #     )
    #
    # librarian_id = token_payload.get("sub")
    # if not librarian_id:
    #     raise HTTPException(
    #         status_code=status.HTTP_401_UNAUTHORIZED,
    #         detail="Invalid token",
    #     )
    #
    # librarian = db.query(Librarian).filter(Librarian.id == int(librarian_id)).first()
    # if not librarian:
    #     raise HTTPException(
    #         status_code=status.HTTP_404_NOT_FOUND,
    #         detail="Librarian not found",
    #     )
    #
    # if not librarian.is_admin:
    #     raise HTTPException(
    #         status_code=status.HTTP_403_FORBIDDEN,
    #         detail="Only administrators can access this endpoint",
    #     )

    librarian = db.query(Librarian).filter(Librarian.is_admin == True).first()
    if not librarian:
        librarian = db.query(Librarian).first()
    if not librarian:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Librarian not found",
        )
    return librarian


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    if month < 1 or month > 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="month must be between 1 and 12",
        )

    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _fetch_report_rows(
    report_type: str,
    start_date: datetime,
    end_date: datetime,
    db: Session,
) -> list[dict]:
    if report_type == "students":
        students = (
            db.query(Student)
            .filter(Student.created_at >= start_date, Student.created_at < end_date)
            .order_by(Student.created_at.desc())
            .all()
        )
        return [
            {
                "id": s.id,
                "full_name": s.full_name,
                "email": s.email,
                "registration_number": s.registration_number,
                "is_active": s.is_active,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in students
        ]

    if report_type == "books":
        rows = (
            db.query(Book, Category.name)
            .outerjoin(BookCategory, BookCategory.book_id == Book.id)
            .outerjoin(Category, Category.id == BookCategory.category_id)
            .filter(Book.created_at >= start_date, Book.created_at < end_date)
            .order_by(Book.created_at.desc())
            .all()
        )
        return [
            {
                "id": book.id,
                "title": book.title,
                "author": book.author,
                "isbn": book.isbn,
                "publication_year": book.publication_year,
                "category_name": category_name,
                "total_copies": book.total_copies,
                "available_copies": book.available_copies,
                "is_available": book.is_available,
                "created_at": book.created_at.isoformat() if book.created_at else None,
            }
            for book, category_name in rows
        ]

    if report_type in {"borrowed_books", "returned_books", "unreturned_books"}:
        query = (
            db.query(BorrowRecord, Student.full_name, Student.email, Book.title, Book.author)
            .join(Student, Student.id == BorrowRecord.student_id)
            .join(Book, Book.id == BorrowRecord.book_id)
        )

        if report_type == "borrowed_books":
            query = query.filter(BorrowRecord.borrowed_at >= start_date, BorrowRecord.borrowed_at < end_date)

        if report_type == "returned_books":
            query = query.filter(
                BorrowRecord.is_returned == True,
                BorrowRecord.returned_at >= start_date,
                BorrowRecord.returned_at < end_date,
            )

        if report_type == "unreturned_books":
            query = query.filter(
                BorrowRecord.is_returned == False,
                BorrowRecord.borrowed_at >= start_date,
                BorrowRecord.borrowed_at < end_date,
            )

        rows = query.order_by(BorrowRecord.borrowed_at.desc()).all()
        return [
            {
                "borrow_record_id": borrow_record.id,
                "student_id": borrow_record.student_id,
                "student_name": student_name,
                "student_email": student_email,
                "book_id": borrow_record.book_id,
                "book_title": book_title,
                "book_author": book_author,
                "borrowed_at": borrow_record.borrowed_at.isoformat() if borrow_record.borrowed_at else None,
                "due_date": borrow_record.due_date.isoformat() if borrow_record.due_date else None,
                "returned_at": borrow_record.returned_at.isoformat() if borrow_record.returned_at else None,
                "is_returned": borrow_record.is_returned,
            }
            for borrow_record, student_name, student_email, book_title, book_author in rows
        ]

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "type must be one of students, books, borrowed_books, "
            "returned_books, unreturned_books"
        ),
    )


def _build_excel_bytes(rows: list[dict], report_type: str) -> bytes:
    try:
        from openpyxl import Workbook
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="openpyxl is required for excel export",
        ) from exc

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = f"{report_type}_report"

    if not rows:
        sheet.append(["No data"])
    else:
        headers = list(rows[0].keys())
        sheet.append(headers)
        for row in rows:
            sheet.append([row.get(header) for header in headers])

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _build_pdf_bytes(rows: list[dict], report_type: str, start_date: datetime, end_date: datetime) -> bytes:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="reportlab is required for pdf export",
        ) from exc

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 40

    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(40, y, f"LMS Monthly {report_type.capitalize()} Report")
    y -= 20
    pdf.setFont("Helvetica", 10)
    pdf.drawString(40, y, f"Range: {start_date.date()} to {end_date.date()} (exclusive)")
    y -= 20
    pdf.drawString(40, y, f"Total records: {len(rows)}")
    y -= 25

    if not rows:
        pdf.drawString(40, y, "No data")
    else:
        headers = list(rows[0].keys())
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawString(40, y, " | ".join(headers[:6]))
        y -= 15
        pdf.setFont("Helvetica", 8)
        for row in rows:
            line = " | ".join(str(row.get(header, ""))[:20] for header in headers[:6])
            pdf.drawString(40, y, line)
            y -= 12
            if y < 40:
                pdf.showPage()
                y = height - 40
                pdf.setFont("Helvetica", 8)

    pdf.save()
    return buffer.getvalue()


def _normalize_header(header: str) -> str:
    return header.strip().lower().replace(" ", "_")


def _get_book_file_path(book_id: int) -> Path | None:
    if not BOOK_FILES_DIR.exists():
        return None

    for file_path in BOOK_FILES_DIR.glob(f"{book_id}.*"):
        if file_path.is_file():
            return file_path
    return None


def _book_row_from_mapping(raw_row: dict) -> dict:
    normalized = {_normalize_header(str(key)): value for key, value in raw_row.items()}

    def pick(*keys: str):
        for key in keys:
            if key in normalized and normalized[key] not in (None, ""):
                return normalized[key]
        return None

    payload = {
        "title": pick("title", "book_title"),
        "author": pick("author", "book_author"),
        "isbn": pick("isbn", "isbn_13", "isbn_10"),
        "description": pick("description", "summary"),
        "publication_year": pick("publication_year", "year", "published_year"),
        "total_copies": pick("total_copies", "copies", "quantity"),
        "category_id": pick("category_id", "category"),
    }

    if payload["publication_year"] is not None:
        payload["publication_year"] = int(payload["publication_year"])
    if payload["total_copies"] is not None:
        payload["total_copies"] = int(payload["total_copies"])
    else:
        payload["total_copies"] = 1
    if payload["category_id"] is not None:
        payload["category_id"] = int(payload["category_id"])

    return payload


def _parse_csv_rows(file_bytes: bytes) -> list[dict]:
    text = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV file must include a header row",
        )
    return [_book_row_from_mapping(row) for row in reader]


def _parse_text_lines_to_rows(text: str) -> list[dict]:
    rows: list[dict] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if "|" not in stripped:
            continue
        parts = [part.strip() for part in stripped.split("|")]
        if len(parts) < 5:
            continue
        row = {
            "title": parts[0],
            "author": parts[1],
            "isbn": parts[2],
            "publication_year": parts[3],
            "total_copies": parts[4],
            "description": parts[5] if len(parts) > 5 and parts[5] else None,
            "category_id": parts[6] if len(parts) > 6 and parts[6] else None,
        }
        rows.append(_book_row_from_mapping(row))
    return rows


def _parse_pdf_rows(file_bytes: bytes) -> list[dict]:
    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="pypdf is required for PDF imports",
        ) from exc

    reader = PdfReader(BytesIO(file_bytes))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    rows = _parse_text_lines_to_rows(extracted)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No importable rows found in PDF. Use one row per line in this format: "
                "title|author|isbn|publication_year|total_copies|description|category_id"
            ),
        )
    return rows


def _parse_docx_rows(file_bytes: bytes) -> list[dict]:
    try:
        from docx import Document
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="python-docx is required for DOCX imports",
        ) from exc

    document = Document(BytesIO(file_bytes))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    rows = _parse_text_lines_to_rows(text)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No importable rows found in DOCX. Use one row per line in this format: "
                "title|author|isbn|publication_year|total_copies|description|category_id"
            ),
        )
    return rows


def _parse_import_file(filename: str, file_bytes: bytes) -> list[dict]:
    lower_name = filename.lower()
    if lower_name.endswith(".csv"):
        return _parse_csv_rows(file_bytes)
    if lower_name.endswith(".pdf"):
        return _parse_pdf_rows(file_bytes)
    if lower_name.endswith(".docx"):
        return _parse_docx_rows(file_bytes)
    if lower_name.endswith(".doc") or lower_name.endswith(".txt"):
        text = file_bytes.decode("utf-8", errors="ignore")
        rows = _parse_text_lines_to_rows(text)
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "No importable rows found. Use one row per line in this format: "
                    "title|author|isbn|publication_year|total_copies|description|category_id"
                ),
            )
        return rows

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Unsupported file format. Supported formats: csv, pdf, docx, doc, txt",
    )


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

    if payload.category_id is not None:
        category = db.query(Category).filter(Category.id == payload.category_id).first()
        if not category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Category not found",
            )

    book = Book(
        title=payload.title,
        author=payload.author,
        isbn=payload.isbn,
        description=payload.description,
        publication_year=payload.publication_year,
        total_copies=payload.total_copies,
        available_copies=payload.total_copies,
        is_available=True,
    )
    db.add(book)
    db.flush()

    if payload.category_id is not None:
        db.add(BookCategory(book_id=book.id, category_id=payload.category_id))

    log_audit_event(
        db,
        action="book_created",
        actor_type="librarian",
        user_id=current_librarian.id,
        resource="book",
        resource_id=book.id,
        details=f"Created book '{book.title}' (ISBN: {book.isbn})",
    )

    db.commit()
    db.refresh(book)

    return _book_to_public(book, db)


@router.post("/books/import", response_model=BookImportResponse, status_code=status.HTTP_201_CREATED)
async def import_books_to_catalog(
    file: UploadFile = File(...),
    default_category_id: int | None = Query(None, ge=1),
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db),
):
    """Import books from CSV/PDF/DOCX/DOC/TXT files."""
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must include a filename",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    if default_category_id is not None:
        default_category = db.query(Category).filter(Category.id == default_category_id).first()
        if not default_category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Default category not found",
            )

    parsed_rows = _parse_import_file(file.filename, file_bytes)
    if not parsed_rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No rows found to import",
        )

    errors: list[dict] = []
    imported_count = 0
    seen_isbns: set[str] = set()

    for row_number, raw_row in enumerate(parsed_rows, start=2):
        try:
            payload = BookCreate.model_validate(raw_row)
        except ValidationError as exc:
            errors.append({"row": row_number, "error": exc.errors()[0]["msg"]})
            continue

        if payload.isbn in seen_isbns:
            errors.append({"row": row_number, "error": "Duplicate ISBN in upload file"})
            continue

        existing_book = db.query(Book).filter(Book.isbn == payload.isbn).first()
        if existing_book:
            errors.append({"row": row_number, "error": "Book with this ISBN already exists"})
            continue

        category_id = payload.category_id if payload.category_id is not None else default_category_id
        if category_id is not None:
            category = db.query(Category).filter(Category.id == category_id).first()
            if not category:
                errors.append({"row": row_number, "error": "Category not found"})
                continue

        book = Book(
            title=payload.title,
            author=payload.author,
            isbn=payload.isbn,
            description=payload.description,
            publication_year=payload.publication_year,
            total_copies=payload.total_copies,
            available_copies=payload.total_copies,
            is_available=True,
        )
        db.add(book)
        db.flush()

        if category_id is not None:
            db.add(BookCategory(book_id=book.id, category_id=category_id))

        seen_isbns.add(payload.isbn)
        imported_count += 1

    db.commit()

    log_audit_event(
        db,
        action="books_imported",
        actor_type="librarian",
        user_id=current_librarian.id,
        resource="book",
        resource_id=None,
        details=(
            f"Imported {imported_count} books from file '{file.filename}'. "
            f"Skipped {len(errors)} rows."
        ),
    )
    db.commit()

    return {
        "message": "Book import completed",
        "total_rows": len(parsed_rows),
        "imported_count": imported_count,
        "skipped_count": len(errors),
        "errors": errors,
    }


@router.post("/books/{book_id}/file", response_model=MessageResponse)
async def upload_book_file(
    book_id: int,
    file: UploadFile = File(...),
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db),
):
    """Upload or replace a downloadable digital copy for a book."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must include a filename",
        )

    suffix = Path(file.filename).suffix.lower()

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    BOOK_FILES_DIR.mkdir(parents=True, exist_ok=True)

    existing_file = _get_book_file_path(book_id)
    if existing_file:
        existing_file.unlink(missing_ok=True)

    stored_file_path = BOOK_FILES_DIR / f"{book_id}{suffix}"
    stored_file_path.write_bytes(file_bytes)

    log_audit_event(
        db,
        action="book_file_uploaded",
        actor_type="librarian",
        user_id=current_librarian.id,
        resource="book",
        resource_id=book.id,
        details=f"Uploaded digital file '{file.filename}' for book_id={book.id}",
    )
    db.commit()

    return {"message": "Book file uploaded successfully"}


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
    if payload.publication_year is not None:
        book.publication_year = payload.publication_year
    if payload.total_copies:
        # Adjust available copies if total changed
        diff = payload.total_copies - book.total_copies
        book.total_copies = payload.total_copies
        book.available_copies = min(book.available_copies + diff, payload.total_copies)

    # Update is_available based on available_copies
    book.is_available = book.available_copies > 0

    if payload.category_id is not None:
        category = db.query(Category).filter(Category.id == payload.category_id).first()
        if not category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Category not found",
            )

        book_category = db.query(BookCategory).filter(BookCategory.book_id == book.id).first()
        if book_category:
            book_category.category_id = payload.category_id
        else:
            db.add(BookCategory(book_id=book.id, category_id=payload.category_id))

    db.commit()
    db.refresh(book)

    return _book_to_public(book, db)


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


@router.post("/books/categories", response_model=CategoryPublic, status_code=status.HTTP_201_CREATED)
def create_book_category(
    payload: CategoryCreate,
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db),
):
    existing_category = db.query(Category).filter(Category.name == payload.name).first()
    if existing_category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category with this name already exists",
        )

    category = Category(name=payload.name, description=payload.description)
    db.add(category)
    db.commit()
    db.refresh(category)

    return category


@router.put("/books/{book_id}/condition", response_model=BookConditionUpdateResponse)
def update_book_condition(
    book_id: int,
    payload: BookConditionUpdateRequest,
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db),
):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )

    condition_value = BookCondition(payload.condition)
    book_condition = db.query(BookConditionStatus).filter(BookConditionStatus.book_id == book_id).first()
    now = datetime.now(timezone.utc)

    if book_condition:
        book_condition.condition = condition_value
        book_condition.updated_by_librarian_id = current_librarian.id
        book_condition.updated_at = now
    else:
        book_condition = BookConditionStatus(
            book_id=book_id,
            condition=condition_value,
            updated_by_librarian_id=current_librarian.id,
            updated_at=now,
        )
        db.add(book_condition)

    db.commit()

    return BookConditionUpdateResponse(
        message="Book condition updated successfully",
        book_id=book_id,
        condition=condition_value.value,
        updated_at=now,
    )


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


@router.patch("/students/{student_id}/suspend", response_model=MessageResponse)
def suspend_student(
    student_id: int,
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db),
):
    """Suspend a student account by setting is_active to False."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found",
        )

    if not student.is_active:
        return {"message": "Student is already suspended"}

    student.is_active = False
    db.commit()

    return {"message": "Student suspended successfully"}


@router.patch("/students/{student_id}/activate", response_model=MessageResponse)
def activate_student(
    student_id: int,
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db),
):
    """Activate a student account by setting is_active to True."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found",
        )

    if student.is_active:
        return {"message": "Student is already active"}

    student.is_active = True
    db.commit()

    return {"message": "Student activated successfully"}


@router.delete("/students/{student_id}", response_model=MessageResponse)
def delete_student(
    student_id: int,
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db),
):
    """Delete a student account if there are no dependent borrowing/fine records."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found",
        )

    active_borrows = db.query(BorrowRecord).filter(
        BorrowRecord.student_id == student_id,
        BorrowRecord.is_returned == False,
    ).count()
    if active_borrows > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete student with active borrowed books",
        )

    pending_requests = db.query(BorrowRequest).filter(
        BorrowRequest.student_id == student_id,
        BorrowRequest.status == BorrowRequestStatus.PENDING,
    ).count()
    if pending_requests > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete student with pending borrow requests",
        )

    unpaid_fines = db.query(Fine).filter(
        Fine.student_id == student_id,
        Fine.is_paid == False,
    ).count()
    if unpaid_fines > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete student with unpaid fines",
        )

    historical_borrow_records = db.query(BorrowRecord).filter(
        BorrowRecord.student_id == student_id,
    ).count()
    if historical_borrow_records > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete student with borrowing history",
        )

    historical_requests = db.query(BorrowRequest).filter(
        BorrowRequest.student_id == student_id,
    ).count()
    if historical_requests > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete student with borrow request history",
        )

    historical_fines = db.query(Fine).filter(
        Fine.student_id == student_id,
    ).count()
    if historical_fines > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete student with fine history",
        )

    db.delete(student)
    db.commit()

    return {"message": "Student deleted successfully"}


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


@router.get("/reports/export")
def export_monthly_report(
    format: str = Query(..., pattern="^(pdf|excel)$"),
    type: str = Query(..., pattern="^(students|books|borrowed_books|returned_books|unreturned_books)$"),
    year: int | None = Query(None, ge=2000, le=2100),
    month: int | None = Query(None, ge=1, le=12),
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    selected_year = year or now.year
    selected_month = month or now.month
    start_date, end_date = _month_bounds(selected_year, selected_month)

    rows = _fetch_report_rows(type, start_date, end_date, db)
    filename_base = f"{type}_report_{selected_year}_{selected_month:02d}"

    if format == "excel":
        content = _build_excel_bytes(rows, type)
        return StreamingResponse(
            BytesIO(content),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename_base}.xlsx"},
        )

    content = _build_pdf_bytes(rows, type, start_date, end_date)
    return StreamingResponse(
        BytesIO(content),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename_base}.pdf"},
    )


@router.get("/reports/custom")
def custom_date_range_report(
    date_from: date = Query(...),
    date_to: date = Query(...),
    type: str = Query(..., pattern="^(students|books|borrowed_books|returned_books|unreturned_books)$"),
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db),
):
    if date_to < date_from:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date_to must be greater than or equal to date_from",
        )

    start_date = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
    end_date = datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc)
    end_date = end_date.replace(microsecond=0)

    rows = _fetch_report_rows(type, start_date, end_date, db)
    return {
        "report_type": type,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "total_records": len(rows),
        "rows": rows,
    }


@router.get("/logs", response_model=list[AuditLogPublic])
def list_audit_logs(
    action: str | None = Query(None),
    user_id: int | None = Query(None, ge=1),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db),
):
    query = db.query(AuditLog)

    if action:
        query = query.filter(AuditLog.action == action)
    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    if date_from is not None:
        start = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
        query = query.filter(AuditLog.created_at >= start)
    if date_to is not None:
        end = datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc)
        query = query.filter(AuditLog.created_at <= end)

    return (
        query.order_by(AuditLog.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/logs/exports")
def export_audit_logs(
    format: str = Query("excel", pattern="^(pdf|excel)$"),
    action: str | None = Query(None),
    user_id: int | None = Query(None, ge=1),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db),
):
    query = db.query(AuditLog)

    if action:
        query = query.filter(AuditLog.action == action)
    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    if date_from is not None:
        start = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
        query = query.filter(AuditLog.created_at >= start)
    if date_to is not None:
        end = datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc)
        query = query.filter(AuditLog.created_at <= end)

    rows = [
        {
            "id": log.id,
            "action": log.action,
            "actor_type": log.actor_type,
            "user_id": log.user_id,
            "resource": log.resource,
            "resource_id": log.resource_id,
            "details": log.details,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in query.order_by(AuditLog.created_at.desc()).all()
    ]

    filename_base = f"audit_logs_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    if format == "excel":
        content = _build_excel_bytes(rows, "audit_logs")
        return StreamingResponse(
            BytesIO(content),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename_base}.xlsx"},
        )

    start_date = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc) if date_from else datetime.now(timezone.utc)
    end_date = datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc) if date_to else datetime.now(timezone.utc)
    content = _build_pdf_bytes(rows, "audit_logs", start_date, end_date)
    return StreamingResponse(
        BytesIO(content),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename_base}.pdf"},
    )
