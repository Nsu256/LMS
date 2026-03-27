from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.mailer import send_verification_email
from app.models import Student
from app.schemas import RegisterResponse, StudentLoginRequest, StudentRegisterRequest, TokenResponse
from app.security import (
    create_access_token,
    create_email_verification_token,
    decode_email_verification_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _build_verification_claims(payload: StudentRegisterRequest) -> dict:
    return {
        "full_name": payload.full_name,
        "email": payload.email,
        "registration_number": payload.registration_number,
        "hashed_password": hash_password(payload.password),
    }


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register_student(payload: StudentRegisterRequest, db: Session = Depends(get_db)):
    if not payload.email.lower().endswith("@gmail.com"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email must end with @gmail.com",
        )

    existing_student = db.query(Student).filter(
        or_(
            Student.email == payload.email,
            Student.registration_number == payload.registration_number,
        )
    ).first()

    if existing_student:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student with this email or registration number already exists",
        )

    verification_token = create_email_verification_token(claims=_build_verification_claims(payload))
    try:
        send_verification_email(payload.email, verification_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed because verification email could not be sent",
        )

    return RegisterResponse(message="Verification email sent. Please verify to complete registration")


@router.post("/resend-verification", response_model=RegisterResponse)
def resend_verification_email(payload: StudentRegisterRequest, db: Session = Depends(get_db)):
    if not payload.email.lower().endswith("@gmail.com"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email must end with @gmail.com",
        )

    existing_student = db.query(Student).filter(
        or_(
            Student.email == payload.email,
            Student.registration_number == payload.registration_number,
        )
    ).first()
    if existing_student:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student already verified. Please login",
        )

    verification_token = create_email_verification_token(claims=_build_verification_claims(payload))
    try:
        send_verification_email(payload.email, verification_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Verification email could not be sent",
        )

    return RegisterResponse(message="Verification email resent. Please verify to complete registration")


@router.post("/login", response_model=TokenResponse)
def login_student(payload: StudentLoginRequest, db: Session = Depends(get_db)):
    student = db.query(Student).filter(Student.email == payload.email).first()

    if not student or not verify_password(payload.password, student.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not student.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before logging in",
        )

    token = create_access_token(subject=str(student.id))
    return TokenResponse(access_token=token, student=student)


@router.get("/verify-email")
def verify_student_email(token: str, db: Session = Depends(get_db)):
    try:
        payload = decode_email_verification_token(token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )

    full_name = payload.get("full_name")
    email = payload.get("email")
    registration_number = payload.get("registration_number")
    hashed_password = payload.get("hashed_password")
    if not all([full_name, email, registration_number, hashed_password]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification token",
        )

    existing_student = db.query(Student).filter(
        or_(
            Student.email == email,
            Student.registration_number == registration_number,
        )
    ).first()
    if existing_student:
        return {"message": "Email already verified"}

    student = Student(
        full_name=full_name,
        email=email,
        registration_number=registration_number,
        hashed_password=hashed_password,
        is_active=True,
    )
    db.add(student)
    db.commit()

    return {"message": "Email verified successfully"}
