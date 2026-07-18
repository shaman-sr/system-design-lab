from sqlmodel import SQLModel, create_engine, Session

DATABASE_URL = "postgresql://postgres:mysecretpassword@db:5432/bank"

engine = create_engine(DATABASE_URL, echo=False)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

# Dependency / helper to handle database sessions
def get_session():
    with Session(engine) as session:
        yield session
