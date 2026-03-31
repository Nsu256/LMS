from app.database import Base, SessionLocal, engine
import app.models as models
import app.security as security


def seed_librarian():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        existing = db.query(models.Librarian).filter(models.Librarian.email == "admin@library.com").first()
        if existing:
            print("Librarian already exists")
            return

        hashed_password = security.hash_password("admin123")
        new_librarian = models.Librarian(
            full_name="Balibaseka Deogiracious",
            email="admin@library.com",
            hashed_password=hashed_password,
            is_active=True,
            is_admin=True,
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