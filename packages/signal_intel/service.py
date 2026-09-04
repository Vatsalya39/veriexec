"""INTENTLOCK Team A — Signal Intelligence service on :8001 (frozen endpoints §13).

POST /v1/process-communication  -> {intent, signals}
POST /v1/extract                -> {intent}
POST /v1/analyze-signals        -> {signals}
POST /v1/freshness/issue        -> freshness token [NOVEL-N18a]
GET  /v1/samples                -> corpus index
GET  /v1/samples/{id}           -> one raw sample (input alongside the verdict)
GET  /healthz
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import CONFIG
from .extract.llm import NullClient, get_client
from .pipeline import process_communication
from .replay.replay import issue_freshness

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"  # packages/signal_intel/samples

app = FastAPI(title="INTENTLOCK Signal Intelligence", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:4173", "http://127.0.0.1:4173",
        "http://localhost:8001", "http://127.0.0.1:8001",
        "http://localhost:8002", "http://127.0.0.1:8002",
        "http://localhost:8003", "http://127.0.0.1:8003",
    ],
    allow_methods=["*"], allow_headers=["*"],
)


class Metadata(BaseModel):
    caller_id: str | None = None
    sender_email: str | None = None
    device_id: str | None = None
    location: str | None = None
    timestamp: str | None = None
    session_id: str | None = None
    claimed_executive_id: str | None = None
    audio_ref: str | None = None
    video_ref: str | None = None
    prior_events: list[dict] = Field(default_factory=list)


class ProcessRequest(BaseModel):
    channel: str
    raw_text_or_transcript: str
    metadata: Metadata = Field(default_factory=Metadata)
    sample_id: str | None = None
    detector_script: dict = Field(default_factory=dict)
    freshness_token: str | None = None
    #: The observed answer to a freshness challenge, when the caller already has it.
    #: `None` = not asked (the dimension abstains). Every corpus sample publishes this
    #: field; without it on the request model the fact could not cross the wire and the
    #: pipeline fell back to hard-coded sample ids.
    freshness_echoed: bool | None = None


def _to_payload(req: "ProcessRequest") -> dict:
    """One request -> pipeline payload mapping, shared by all three POST endpoints.

    The three handlers had three copies of this dict; they had already drifted apart once
    and any new field had to be added in three places.
    """
    return {"channel": req.channel, "raw_text_or_transcript": req.raw_text_or_transcript,
            "metadata": req.metadata.model_dump(), "sample_id": req.sample_id,
            "detector_script": req.detector_script, "freshness_token": req.freshness_token,
            "freshness_echoed": req.freshness_echoed}


class ExtractRequest(ProcessRequest):
    pass


class AnalyzeRequest(ProcessRequest):
    pass


class FreshnessRequest(BaseModel):
    transaction_id: str


@app.get("/healthz")
def healthz():
    # The mode banner must state what the extraction path actually does, not what the key
    # store guesses: Ollama needs no API key, so the old `if CONFIG.llm_api_key` reported
    # "offline" while the model ran. The client itself is the truth here.
    active = not isinstance(get_client(), NullClient)
    return {"ok": True, "service": "signal", "version": "1.0.0",
            "mode": f"{CONFIG.mode}+llm" if active else "offline",
            "policy_version": CONFIG.policy_version}


@app.post("/v1/process-communication")
def process_communication_ep(req: ProcessRequest):
    return process_communication(_to_payload(req))


@app.post("/v1/extract")
def extract_ep(req: ExtractRequest):
    return {"intent": process_communication(_to_payload(req))["intent"]}


@app.post("/v1/analyze-signals")
def analyze_signals_ep(req: AnalyzeRequest):
    return {"signals": process_communication(_to_payload(req))["signals"]}


@app.post("/v1/freshness/issue")
def freshness_ep(req: FreshnessRequest):
    return issue_freshness(req.transaction_id)


@app.get("/v1/samples")
def list_samples():
    out = []
    for path in sorted(SAMPLES_DIR.glob("S*.json")):
        s = json.loads(path.read_text(encoding="utf-8"))
        out.append({"sample_id": s["sample_id"], "label": s["label"], "class": s["class"],
                    "hero": s["hero"], "channel": s["channel"], "narration": s["narration"],
                    "expected_decision": s["expected_decision"]})
    return out


@app.get("/v1/samples/{sample_id}")
def get_sample(sample_id: str):
    path = SAMPLES_DIR / f"{sample_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="sample not found")
    return json.loads(path.read_text(encoding="utf-8"))
