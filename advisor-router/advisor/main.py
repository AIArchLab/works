import os
from typing import Optional
from fastapi import FastAPI
from pydantic import BaseModel
from .core import Advisor

app = FastAPI(title="model-advisor")
advisor = Advisor(rules=os.getenv("RULES", "rules.yaml"),
                  models=os.getenv("MODELS", "models.yaml"),
                  log=os.getenv("DECISION_LOG", "decisions.jsonl"))

class DecideReq(BaseModel):
    task_id: str
    step_type: str
    text: str = ""
    tokens: int = 0
    phase: str = "entry"              # entry | reask
    current_tier: Optional[str] = None
    struggle: Optional[str] = None    # e.g. "tool_error_x3", "loop_detected"

class DecideResp(BaseModel):
    tier: str
    model: str
    source: str                        # why: rule:<name> | classifier | default | upgrade(...) | sticky(...)

@app.post("/decide", response_model=DecideResp)
def decide(req: DecideReq):
    return advisor.decide(**req.model_dump())

@app.get("/health")
def health(): return {"ok": True}
