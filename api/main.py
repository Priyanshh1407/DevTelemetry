import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from api.routes import router  # noqa: E402

app = FastAPI(title="DevTelemetry API")

# Only the dashboard may call this API from a browser. FRONTEND_URL is the deployed
# dashboard (comma-separated for several); the Vite dev server is always allowed.
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
frontend_origins = [o.strip().rstrip("/") for o in os.getenv("FRONTEND_URL", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins + DEV_ORIGINS,
    allow_credentials=False,  # auth is a header token, not cookies
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Admin-Token"],
)

# Connect our routes
app.include_router(router, prefix="/api")

@app.get("/")
def read_root():
    return {"status": "API is running"}
