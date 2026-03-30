from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.mailer import send_password_reset_email, send_verification_email
from app.models import Librarian, Student
from app.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    RegisterResponse,
    ResetPasswordRequest,
    StudentLoginRequest,
    StudentRegisterRequest,
    TokenResponse,
)
from app.security import (
    create_access_token,
    create_email_verification_token,
    create_password_reset_token,
    decode_token,
    decode_password_reset_token,
    decode_email_verification_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearer()


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

    # verification_token = create_email_verification_token(claims=_build_verification_claims(payload))
    # try:
    #     send_verification_email(payload.email, verification_token)
    # except Exception:
    #     raise HTTPException(
    #         status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    #         detail="Registration failed because verification email could not be sent",
    #     )

    student = Student(
        full_name=payload.full_name,
        email=payload.email,
        registration_number=payload.registration_number,
        hashed_password=hash_password(payload.password),
        is_active=True,
    )
    db.add(student)
    db.commit()

    return RegisterResponse(message="Registration successful")



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

    # verification_token = create_email_verification_token(claims=_build_verification_claims(payload))
    # try:
    #     send_verification_email(payload.email, verification_token)
    # except Exception:
    #     raise HTTPException(
    #         status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    #         detail="Verification email could not be sent",
    #     )

    return RegisterResponse(message="Verification bypassed")



@router.post("/login", response_model=TokenResponse)
def login_users(payload: StudentLoginRequest, db: Session = Depends(get_db)):
    student = db.query(Student).filter(Student.email == payload.email).first()
    if student:
        if not verify_password(payload.password, student.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        # if not student.is_active:
        #     raise HTTPException(
        #         status_code=status.HTTP_403_FORBIDDEN,
        #         detail="Please verify your email before logging in",
        #     )

        token = create_access_token(subject=str(student.id))
        return TokenResponse(access_token=token, user_type="student", student=student)

    librarian = db.query(Librarian).filter(Librarian.email == payload.email).first()
    if not librarian or not verify_password(payload.password, librarian.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # if not librarian.is_active:
    #     raise HTTPException(
    #         status_code=status.HTTP_403_FORBIDDEN,
    #         detail="Librarian account is inactive",
    #     )

    token = create_access_token(subject=str(librarian.id))
    return TokenResponse(access_token=token, user_type="librarian", librarian=librarian)



@router.post("/logout", response_model=RegisterResponse)
def logout_users(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        decode_token(credentials.credentials)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    return RegisterResponse(message="Logged out successfully")



@router.post("/forgot-password", response_model=RegisterResponse)
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    student = db.query(Student).filter(Student.email == payload.email).first()

    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    reset_token = create_password_reset_token(subject=str(student.id))
    try:
        send_password_reset_email(student.email, reset_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password reset email could not be sent",
        )

    return RegisterResponse(message="Password reset email has been sent")



@router.post("/reset-password", response_model=RegisterResponse)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    try:
        token_payload = decode_password_reset_token(payload.token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired password reset token",
        )

    student_id = token_payload.get("sub")
    if not student_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid password reset token",
        )

    student = db.query(Student).filter(Student.id == int(student_id)).first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    student.hashed_password = hash_password(payload.new_password)
    db.commit()

    return RegisterResponse(message="Password reset successful")



@router.post("/change-password", response_model=RegisterResponse)
def change_password(
    payload: ChangePasswordRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
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
            detail="Account not found",
        )

    if not verify_password(payload.current_password, student.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    if payload.current_password == payload.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password",
        )

    student.hashed_password = hash_password(payload.new_password)
    db.commit()

    return RegisterResponse(message="Password changed successfully")



@router.get("/verify-email")
def verify_student_email(token: str, db: Session = Depends(get_db)):
    # try:
    #     payload = decode_email_verification_token(token)
    # except ValueError:
    #     raise HTTPException(
    #         status_code=status.HTTP_400_BAD_REQUEST,
    #         detail="Invalid or expired verification token",
    #     )
    #
    # full_name = payload.get("full_name")
    # email = payload.get("email")
    # registration_number = payload.get("registration_number")
    # hashed_password = payload.get("hashed_password")
    # if not all([full_name, email, registration_number, hashed_password]):
    #     raise HTTPException(
    #         status_code=status.HTTP_400_BAD_REQUEST,
    #         detail="Invalid verification token",
    #     )
    #
    # existing_student = db.query(Student).filter(
    #     or_(
    #         Student.email == email,
    #         Student.registration_number == registration_number,
    #     )
    # ).first()
    # if existing_student:
    #     return {"message": "Email already verified"}
    #
    # student = Student(
    #     full_name=full_name,
    #     email=email,
    #     registration_number=registration_number,
    #     hashed_password=hashed_password,
    #     is_active=True,
    # )
    # db.add(student)
    # db.commit()

    return {"message": "Email verified successfully"}
    
    