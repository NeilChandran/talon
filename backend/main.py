from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env", override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import leads, outreach, prospecting, sequences
from routers import linkedin_auth
from routers import analytics

app = FastAPI(title="Talon API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(leads.router, prefix="/leads", tags=["leads"])
app.include_router(prospecting.router, prefix="/prospecting", tags=["prospecting"])
app.include_router(outreach.router, prefix="/outreach", tags=["outreach"])
app.include_router(sequences.router, prefix="/sequences", tags=["sequences"])
app.include_router(linkedin_auth.router, prefix="/linkedin", tags=["linkedin"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "talon"}
