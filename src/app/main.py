from fastapi import FastAPI

from src.app.config.config import create_db_and_tables
from src.app.controllers.controller import router

app = FastAPI()
create_db_and_tables()

app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
