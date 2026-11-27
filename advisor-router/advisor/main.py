import os
from pathlib import Path
from typing import Literal, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from .core import Advisor

DATA = Path(__file__).parent / "data"   # packaged default rules.yaml / models.yaml

app = FastAPI(title="model-advisor")
advisor = Advisor(rules=os.getenv("RULES") or str(DATA / "rules.yaml"),
                  models=os.getenv("MODELS") or str(DATA / "models.yaml"),
                  log=os.getenv("DECISION_LOG", "decisions.jsonl"))

class DecideReq(BaseModel):
    task_id: str
    step_type: str
    text: str = ""
    tokens: int = Field(0, ge=0)
    phase: Literal["entry", "reask"] = "entry"
    current_tier: Optional[str] = None   # must be one of the configured tiers
    struggle: Optional[str] = None       # e.g. "tool_error_x3"; required when phase=reask

class DecideResp(BaseModel):
    tier: str
    model: str
    source: str                          # rule | classifier | default
    matched_rule: Optional[str] = None   # rule name when source=rule, else null
    clamp: Literal["sticky", "upgrade", "ceiling", "none"]

@app.post("/decide", response_model=DecideResp)
def decide(req: DecideReq):
    if req.current_tier is not None and req.current_tier not in advisor.reg.tiers:
        raise HTTPException(422, f"current_tier must be one of {advisor.reg.tiers}")
    if req.phase == "reask" and req.current_tier is None:
        raise HTTPException(422, "current_tier is required when phase=reask")
    if req.phase == "reask" and not req.struggle:
        raise HTTPException(422, "struggle is required when phase=reask")
    return advisor.decide(**req.model_dump())

@app.get("/health")
def health(): return {"ok": True}
