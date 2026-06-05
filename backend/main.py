from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env", override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from middleware_auth import AuthMiddleware
from routers import leads, outreach, prospecting, sequences
from routers import linkedin_auth
from routers import analytics
from routers import campaigns, agent, explore, workspaces, outreach_export, searches

app = FastAPI(title="Talon API", version="2.0.0")

app.add_middleware(AuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "Authorization"],
)

app.include_router(leads.router, prefix="/leads", tags=["leads"])
app.include_router(prospecting.router, prefix="/prospecting", tags=["prospecting"])
app.include_router(outreach.router, prefix="/outreach", tags=["outreach"])
app.include_router(sequences.router, prefix="/sequences", tags=["sequences"])
app.include_router(linkedin_auth.router, prefix="/linkedin", tags=["linkedin"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
app.include_router(campaigns.router, prefix="/campaigns", tags=["campaigns"])
app.include_router(agent.router, prefix="/agent", tags=["agent"])
app.include_router(explore.router, prefix="/explore", tags=["explore"])
app.include_router(workspaces.router, prefix="/workspaces", tags=["workspaces"])
app.include_router(outreach_export.router, prefix="/outreach-export", tags=["outreach-export"])
app.include_router(searches.router, prefix="/searches", tags=["searches"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "talon"}
