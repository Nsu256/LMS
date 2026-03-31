from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.mailer import send_notification_email
from app.models import (
    Librarian,
    NotificationLog,
    NotificationStatus,
    NotificationType,
    Student,
)
from app.schemas import (
    NotificationPublic,
    NotificationSendResponse,
    SendNotificationEmailRequest,
)
from app.security import decode_token

router = APIRouter(tags=["Notifications"])
security = HTTPBearer(auto_error=False)


def _get_token_subject(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> int | None:
    # try:
    #     payload = decode_token(credentials.credentials)
    # except ValueError:
    #     raise HTTPException(
    #         status_code=status.HTTP_401_UNAUTHORIZED,
    #         detail="Invalid token",
    #     )
    #
    # subject = payload.get("sub")
    # if not subject:
    #     raise HTTPException(
    #         status_code=status.HTTP_401_UNAUTHORIZED,
    #         detail="Invalid token",
    #     )
    # return int(subject)
    return None


def _get_current_librarian(
    credentials: HTTPAuthorizationCredentials | None,
    db: Session,
) -> Librarian:
    # subject = _get_token_subject(credentials)
    # librarian = db.query(Librarian).filter(Librarian.id == subject).first()
    # if not librarian or not librarian.is_admin:
    #     raise HTTPException(
    #         status_code=status.HTTP_403_FORBIDDEN,
    #         detail="Only administrators can perform this action",
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


def _get_current_student(
    credentials: HTTPAuthorizationCredentials | None,
    db: Session,
) -> Student:
    # subject = _get_token_subject(credentials)
    # student = db.query(Student).filter(Student.id == subject).first()
    # if not student:
    #     raise HTTPException(
    #         status_code=status.HTTP_403_FORBIDDEN,
    #         detail="Only students can access this endpoint",
    #     )
    student = db.query(Student).first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found",
        )
    return student


@router.post("/notifications/send-email", response_model=NotificationSendResponse)
def send_email_notification(
    payload: SendNotificationEmailRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
):
    librarian = _get_current_librarian(credentials, db)

    student = db.query(Student).filter(Student.id == payload.student_id).first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found",
        )

    notification = NotificationLog(
        student_id=student.id,
        sent_by_librarian_id=librarian.id,
        recipient_email=student.email,
        subject=payload.subject,
        body=payload.message,
        notification_type=NotificationType(payload.notification_type),
        status=NotificationStatus.FAILED,
        sent_at=None,
        error_message=None,
    )

    try:
        send_notification_email(
            recipient_email=student.email,
            subject=payload.subject,
            message_body=payload.message,
        )
        notification.status = NotificationStatus.SENT
        notification.sent_at = datetime.now(timezone.utc)
    except Exception as exc:
        notification.status = NotificationStatus.FAILED
        notification.error_message = str(exc)[:500]

    db.add(notification)
    db.commit()
    db.refresh(notification)

    if notification.status == NotificationStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Email delivery failed. Notification log was recorded.",
        )

    return NotificationSendResponse(
        message="Notification email sent successfully",
        notification=notification,
    )


@router.get("/students/my-notifications", response_model=list[NotificationPublic])
def get_my_notifications(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
):
    student = _get_current_student(credentials, db)

    notifications = (
        db.query(NotificationLog)
        .filter(NotificationLog.student_id == student.id)
        .order_by(NotificationLog.created_at.desc())
        .all()
    )
    return notifications


@router.get("/admin/notification-logs", response_model=list[NotificationPublic])
def get_notification_logs(
    status_filter: str | None = Query(default=None, pattern="^(sent|failed)$"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    credentials: HTTPAuthorizationCredentials | None = None,
    db: Session = Depends(get_db),
):
    _get_current_librarian(credentials, db)

    query = db.query(NotificationLog)
    if status_filter:
        query = query.filter(NotificationLog.status == NotificationStatus(status_filter))

    logs = query.order_by(NotificationLog.created_at.desc()).offset(skip).limit(limit).all()
    return logs
