from sqlachemy.orm import Session
from database import SessionLocal, engine
import models, security,schemas


def seed_librarian():
    db = SessionLocal()
    try:
        existing = db.query(models.Librarian).filter(models.Librarian.email == "admin@library.com").first()
        if existing:
            print("Librarian already exists")
            return
            hashed_password = security.get_password_hash("admin123")
            new_librarian = models.Librarian(
                full_name="Balibaseka Deogiracious",
                email="deolee@library.com",
                hashed_password=hashed_password,
                is_active=True,
                is_admin=True
            )
            db.add(new_librarian)
            db.commit()
            print("Librarian added successfully")
    except Exception as e:
        print(f"Error seeding database: {e}")
    finally:
        db.close()


        if __name__ == "__main__":
            seed_librarian()