from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from app.database import get_db
from app.models import Book, BorrowRequest, BorrowRecord, Fine, Student, Librarian
from app.schemas import (
    TopBorrower,
    StudentStats,
    MostBorrowedBook,
    BookInventoryStats,
    BorrowingTrendsStats,
    BorrowingTrend,
    FineStats,
    TopDefaulter,
    OverdueStats,
    SystemHealthStats,
    DetailedReport,
    MessageResponse,
)
from app.security import decode_token

router = APIRouter(prefix="/admin/stats", tags=["Statistics"])
security = HTTPBearer()


def get_current_librarian(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)) -> Librarian:
    """Verify admin librarian access."""
    try:
        token_payload = decode_token(credentials.credentials)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    librarian_id = token_payload.get("sub")
    librarian = db.query(Librarian).filter(Librarian.id == int(librarian_id)).first()
    if not librarian or not librarian.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only administrators can access this endpoint")

    return librarian


# ==================== USER STATISTICS ====================

@router.get("/users/total", response_model=dict)
def get_total_users_count(
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """Get total number of users in the system."""
    total_students = db.query(func.count(Student.id)).scalar() or 0
    total_librarians = db.query(func.count(Librarian.id)).scalar() or 0

    return {
        "total_students": total_students,
        "total_librarians": total_librarians,
        "total_users": total_students + total_librarians,
    }


# ==================== STUDENT STATISTICS ====================

@router.get("/students/active", response_model=dict)
def get_active_students_count(
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """Get count of active students."""
    count = db.query(func.count(Student.id)).filter(Student.is_active == True).scalar() or 0
    return {"active_students": count}


@router.get("/students/top-borrowers", response_model=StudentStats)
def get_top_borrowers(
    limit: int = Query(10, ge=1, le=100),
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """Get top borrowers."""
    top_borrowers_query = db.query(
        Student.id,
        Student.full_name,
        Student.email,
        func.count(BorrowRecord.id).label('borrow_count')
    ).join(BorrowRecord, Student.id == BorrowRecord.student_id).group_by(
        Student.id
    ).order_by(func.count(BorrowRecord.id).desc()).limit(limit).all()

    top_borrowers = [
        TopBorrower(
            student_id=s[0],
            full_name=s[1],
            email=s[2],
            borrow_count=s[3] or 0
        ) for s in top_borrowers_query
    ]

    total_active = db.query(func.count(Student.id)).filter(Student.is_active == True).scalar() or 0
    defaulters = db.query(func.count(Student.id.distinct())).join(
        Fine, Student.id == Fine.student_id
    ).filter(Fine.is_paid == False).scalar() or 0

    compliance_rate = ((total_active - defaulters) / total_active * 100) if total_active > 0 else 0

    return StudentStats(
        total_active_students=total_active,
        top_borrowers=top_borrowers,
        defaulters_count=defaulters,
        compliance_rate=compliance_rate
    )


@router.get("/students/defaulters", response_model=list[TopDefaulter])
def get_defaulters(
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """Get students with unpaid fines ranked by amount owed."""
    defaulters_query = db.query(
        Student.id,
        Student.full_name,
        Student.email,
        func.sum(Fine.amount).label('outstanding_amount'),
        func.count(BorrowRecord.id.distinct()).label('overdue_count')
    ).join(Fine, Student.id == Fine.student_id).join(
        BorrowRecord, and_(
            Student.id == BorrowRecord.student_id,
            BorrowRecord.is_returned == False,
            BorrowRecord.due_date < datetime.now(timezone.utc)
        ), isouter=True
    ).filter(Fine.is_paid == False).group_by(
        Student.id
    ).order_by(func.sum(Fine.amount).desc()).all()

    return [
        TopDefaulter(
            student_id=d[0],
            full_name=d[1],
            email=d[2],
            outstanding_amount=float(d[3] or 0),
            overdue_books_count=d[4] or 0
        ) for d in defaulters_query
    ]


# ==================== BOOK STATISTICS ====================

@router.get("/books/most-borrowed", response_model=list[MostBorrowedBook])
def get_most_borrowed_books(
    limit: int = Query(10, ge=1, le=100),
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """Get most borrowed books."""
    most_borrowed = db.query(
        Book.id,
        Book.title,
        Book.author,
        func.count(BorrowRecord.id).label('borrow_count'),
        Book.total_copies,
        Book.available_copies
    ).join(BorrowRecord, Book.id == BorrowRecord.book_id).group_by(
        Book.id
    ).order_by(func.count(BorrowRecord.id).desc()).limit(limit).all()

    return [
        MostBorrowedBook(
            book_id=b[0],
            title=b[1],
            author=b[2],
            borrow_count=b[3] or 0,
            availability_percentage=(b[5] / b[4] * 100) if b[4] > 0 else 0
        ) for b in most_borrowed
    ]


@router.get("/books/least-borrowed", response_model=list[MostBorrowedBook])
def get_least_borrowed_books(
    limit: int = Query(10, ge=1, le=100),
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """Get least borrowed books (unused books)."""
    least_borrowed = db.query(
        Book.id,
        Book.title,
        Book.author,
        func.count(BorrowRecord.id).label('borrow_count'),
        Book.total_copies,
        Book.available_copies
    ).join(BorrowRecord, Book.id == BorrowRecord.book_id, isouter=True).group_by(
        Book.id
    ).order_by(func.count(BorrowRecord.id).asc()).limit(limit).all()

    return [
        MostBorrowedBook(
            book_id=b[0],
            title=b[1],
            author=b[2],
            borrow_count=b[3] or 0,
            availability_percentage=(b[5] / b[4] * 100) if b[4] > 0 else 0
        ) for b in least_borrowed
    ]


@router.get("/books/inventory", response_model=BookInventoryStats)
def get_book_inventory_stats(
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """Get overall book inventory statistics."""
    total_books = db.query(func.count(Book.id)).scalar() or 0
    total_copies = db.query(func.sum(Book.total_copies)).scalar() or 0
    available_copies = db.query(func.sum(Book.available_copies)).scalar() or 0
    borrowed_copies = total_copies - available_copies if total_copies > 0 else 0
    zero_availability = db.query(func.count(Book.id)).filter(Book.available_copies == 0).scalar() or 0

    return BookInventoryStats(
        total_books=total_books,
        total_copies=total_copies,
        available_copies=available_copies,
        borrowed_copies=borrowed_copies,
        books_with_zero_availability=zero_availability
    )


# ==================== BORROWING ANALYTICS ====================

@router.get("/borrows/trends", response_model=BorrowingTrendsStats)
def get_borrowing_trends(
    days: int = Query(7, ge=1, le=90),
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """Get borrowing trends over specified days."""
    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=days)

    # Average borrow duration
    avg_duration = db.query(
        func.avg(func.julianday(BorrowRecord.returned_at) - func.julianday(BorrowRecord.borrowed_at))
    ).filter(
        BorrowRecord.is_returned == True,
        BorrowRecord.returned_at >= start_date
    ).scalar() or 0

    # On-time vs late returns
    total_returns = db.query(func.count(BorrowRecord.id)).filter(
        BorrowRecord.is_returned == True,
        BorrowRecord.returned_at >= start_date
    ).scalar() or 0

    on_time_returns = db.query(func.count(BorrowRecord.id)).filter(
        BorrowRecord.is_returned == True,
        BorrowRecord.returned_at <= BorrowRecord.due_date,
        BorrowRecord.returned_at >= start_date
    ).scalar() or 0

    on_time_rate = (on_time_returns / total_returns * 100) if total_returns > 0 else 0
    late_rate = 100 - on_time_rate

    # Daily trends
    trends_data = []
    for i in range(days):
        day = start_date + timedelta(days=i)
        day_end = day + timedelta(days=1)

        borrow_count = db.query(func.count(BorrowRecord.id)).filter(
            BorrowRecord.borrowed_at >= day,
            BorrowRecord.borrowed_at < day_end
        ).scalar() or 0

        return_count = db.query(func.count(BorrowRecord.id)).filter(
            BorrowRecord.returned_at >= day,
            BorrowRecord.returned_at < day_end
        ).scalar() or 0

        request_count = db.query(func.count(BorrowRequest.id)).filter(
            BorrowRequest.requested_at >= day,
            BorrowRequest.requested_at < day_end
        ).scalar() or 0

        trends_data.append(BorrowingTrend(
            date=day.strftime("%Y-%m-%d"),
            borrow_count=borrow_count,
            return_count=return_count,
            new_requests=request_count
        ))

    return BorrowingTrendsStats(
        average_borrow_duration_days=round(float(avg_duration), 2),
        on_time_return_rate=round(on_time_rate, 2),
        late_return_rate=round(late_rate, 2),
        trends=trends_data
    )


# ==================== FINE & REVENUE ====================

@router.get("/fines/summary", response_model=FineStats)
def get_fine_statistics(
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """Get fine statistics."""
    outstanding = db.query(func.sum(Fine.amount)).filter(Fine.is_paid == False).scalar() or 0
    collected = db.query(func.sum(Fine.amount)).filter(Fine.is_paid == True).scalar() or 0
    unpaid_count = db.query(func.count(Fine.id)).filter(Fine.is_paid == False).scalar() or 0
    paid_count = db.query(func.count(Fine.id)).filter(Fine.is_paid == True).scalar() or 0
    total_fines = unpaid_count + paid_count
    avg_fine = (outstanding + collected) / total_fines if total_fines > 0 else 0

    return FineStats(
        total_outstanding_fines=float(outstanding),
        total_collected_fines=float(collected),
        fine_count_unpaid=unpaid_count,
        fine_count_paid=paid_count,
        average_fine_amount=round(float(avg_fine), 2)
    )


@router.get("/fines/top-defaulters", response_model=list[TopDefaulter])
def get_top_defaulters(
    limit: int = Query(10, ge=1, le=100),
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """Get top defaulters by fine amount."""
    top_defaulters = db.query(
        Student.id,
        Student.full_name,
        Student.email,
        func.sum(Fine.amount).label('outstanding'),
        func.count(func.distinct(BorrowRecord.id)).label('overdue_count')
    ).join(Fine, Student.id == Fine.student_id).join(
        BorrowRecord, and_(
            Student.id == BorrowRecord.student_id,
            BorrowRecord.is_returned == False,
            BorrowRecord.due_date < datetime.now(timezone.utc)
        ), isouter=True
    ).filter(Fine.is_paid == False).group_by(
        Student.id
    ).order_by(func.sum(Fine.amount).desc()).limit(limit).all()

    return [
        TopDefaulter(
            student_id=t[0],
            full_name=t[1],
            email=t[2],
            outstanding_amount=float(t[3] or 0),
            overdue_books_count=t[4] or 0
        ) for t in top_defaulters
    ]


# ==================== OVERDUE MANAGEMENT ====================

@router.get("/overdue/summary", response_model=OverdueStats)
def get_overdue_summary(
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """Get overdue books summary."""
    now = datetime.now(timezone.utc)

    total_overdue = db.query(func.count(BorrowRecord.id)).filter(
        BorrowRecord.is_returned == False,
        BorrowRecord.due_date < now
    ).scalar() or 0

    days_1_7 = db.query(func.count(BorrowRecord.id)).filter(
        BorrowRecord.is_returned == False,
        BorrowRecord.due_date < now,
        BorrowRecord.due_date >= now - timedelta(days=7)
    ).scalar() or 0

    days_8_14 = db.query(func.count(BorrowRecord.id)).filter(
        BorrowRecord.is_returned == False,
        BorrowRecord.due_date < now - timedelta(days=7),
        BorrowRecord.due_date >= now - timedelta(days=14)
    ).scalar() or 0

    days_15_plus = db.query(func.count(BorrowRecord.id)).filter(
        BorrowRecord.is_returned == False,
        BorrowRecord.due_date < now - timedelta(days=14)
    ).scalar() or 0

    overdue_by_student = db.query(
        Student.id,
        Student.full_name,
        Student.email,
        func.sum(Fine.amount).label('outstanding'),
        func.count(BorrowRecord.id).label('overdue_count')
    ).join(BorrowRecord, Student.id == BorrowRecord.student_id).join(
        Fine, Student.id == Fine.student_id, isouter=True
    ).filter(
        BorrowRecord.is_returned == False,
        BorrowRecord.due_date < now,
        Fine.is_paid == False
    ).group_by(Student.id).order_by(func.count(BorrowRecord.id).desc()).limit(10).all()

    return OverdueStats(
        total_overdue_books=total_overdue,
        books_1_to_7_days_late=days_1_7,
        books_8_to_14_days_late=days_8_14,
        books_15_plus_days_late=days_15_plus,
        overdue_by_student=[
            TopDefaulter(
                student_id=o[0],
                full_name=o[1],
                email=o[2],
                outstanding_amount=float(o[3] or 0),
                overdue_books_count=o[4] or 0
            ) for o in overdue_by_student
        ]
    )


# ==================== SYSTEM HEALTH ====================

@router.get("/health", response_model=SystemHealthStats)
def get_system_health(
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """Get system health metrics."""
    from app.models import BorrowRequestStatus

    pending_requests = db.query(func.count(BorrowRequest.id)).filter(
        BorrowRequest.status == BorrowRequestStatus.PENDING
    ).scalar() or 0

    active_borrows = db.query(func.count(BorrowRecord.id)).filter(
        BorrowRecord.is_returned == False
    ).scalar() or 0

    # Average approval time (in hours)
    avg_approval = db.query(
        func.avg(func.julianday(BorrowRequest.approved_at) - func.julianday(BorrowRequest.requested_at))
    ).filter(
        BorrowRequest.status == BorrowRequestStatus.APPROVED,
        BorrowRequest.approved_at.isnot(None)
    ).scalar() or 0

    avg_hours = float(avg_approval) * 24 if avg_approval else 0

    return SystemHealthStats(
        pending_requests=pending_requests,
        active_borrows=active_borrows,
        average_approval_time_hours=round(avg_hours, 2),
        system_uptime="Active"
    )


# ==================== COMPREHENSIVE DASHBOARD ====================

@router.get("/dashboard", response_model=dict)
def get_comprehensive_dashboard(
    current_librarian: Librarian = Depends(get_current_librarian),
    db: Session = Depends(get_db)
):
    """Get comprehensive dashboard with all statistics."""
    now = datetime.now(timezone.utc)

    # Quick stats
    total_books = db.query(func.count(Book.id)).scalar() or 0
    available_books = db.query(func.sum(Book.available_copies)).scalar() or 0
    active_students = db.query(func.count(Student.id)).filter(Student.is_active == True).scalar() or 0
    active_borrows = db.query(func.count(BorrowRecord.id)).filter(BorrowRecord.is_returned == False).scalar() or 0
    overdue_books = db.query(func.count(BorrowRecord.id)).filter(
        BorrowRecord.is_returned == False,
        BorrowRecord.due_date < now
    ).scalar() or 0
    outstanding_fines = db.query(func.sum(Fine.amount)).filter(Fine.is_paid == False).scalar() or 0
    pending_requests = db.query(func.count(BorrowRequest.id)).filter(
        BorrowRequest.status == db.query(func.literal("pending")).scalar()
    ).scalar() or 0

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_books": total_books,
            "available_books": available_books,
            "borrowed_books": (total_books - available_books) if total_books > 0 else 0,
            "active_students": active_students,
            "active_borrows": active_borrows,
            "overdue_books": overdue_books,
            "outstanding_fines": float(outstanding_fines or 0),
            "pending_requests": pending_requests,
        }
    }
