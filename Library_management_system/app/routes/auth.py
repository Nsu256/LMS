from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Student
from app.schemas import StudentLoginRequest, StudentRegisterRequest, TokenResponse
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register_student(payload: StudentRegisterRequest, db: Session = Depends(get_db)):
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

    student = Student(
        full_name=payload.full_name,
        email=payload.email,
        registration_number=payload.registration_number,
        hashed_password=hash_password(payload.password),
    )
    db.add(student)
    db.commit()
    db.refresh(student)

    token = create_access_token(subject=str(student.id))
    return TokenResponse(access_token=token, student=student)


@router.post("/login", response_model=TokenResponse)
def login_student(payload: StudentLoginRequest, db: Session = Depends(get_db)):
    student = db.query(Student).filter(Student.email == payload.email).first()

    if not student or not verify_password(payload.password, student.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(subject=str(student.id))
    return TokenResponse(access_token=token, student=student)
