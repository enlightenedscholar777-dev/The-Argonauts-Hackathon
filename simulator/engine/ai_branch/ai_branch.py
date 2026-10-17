"""
Level 2 — AI branch skeleton (hybrid retrieval + LLM).

Implements two operating modes described in structure.md:
  - Fast mode  : extract information from notes; short grounded explanations.
  - Deliberative mode : compare allowed alternatives when evidence is ambiguous.

The class is intentionally decoupled from the CPU assessment path.
The numerical core produces a decision recommendation *before* this branch
runs; the AI branch can refine or explain but never delays a required handoff.

Retrieval
---------
BM25 + BGE-small-en-v1.5 + Reciprocal Rank Fusion (RRF) over approved
procedure documents.  For the hackathon, the index is populated with a small
in-memory corpus of simulated procedures.

LLM
---
IBM Granite 4.2 3B (preferred) or Qwen3.5 4B, served via a local vLLM
endpoint.  The client sends a compact state snapshot and receives a
structured JSON response: action_id, evidence_ids, uncertainty, explanation.

All AI proposals go through the action verifier before reaching the operator.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Retrieval result
# ---------------------------------------------------------------------------

@dataclass
class RetrievedPassage:
    doc_id:     str
    title:      str
    text:       str
    rrf_score:  float   # Reciprocal Rank Fusion combined score


# ---------------------------------------------------------------------------
# AI branch proposal
# ---------------------------------------------------------------------------

@dataclass
class AIProposal:
    """
    Candidate action or explanation returned by the AI branch.

    All fields are optional — the verifier rejects incomplete proposals.
    ``is_thinking_mode`` indicates whether the model used deliberative
    (full-thinking) or fast (non-thinking) inference settings.
    """
    action_id:          Optional[str]        = None
    evidence_ids:       List[str]            = field(default_factory=list)
    uncertainty_note:   Optional[str]        = None
    explanation:        Optional[str]        = None
    retrieved_passages: List[RetrievedPassage] = field(default_factory=list)
    is_thinking_mode:   bool                 = False
    raw_model_output:   Optional[str]        = None


# ---------------------------------------------------------------------------
# Stub retriever
# ---------------------------------------------------------------------------

class HybridRetriever:
    """
    BM25 + dense embedding retriever with Reciprocal Rank Fusion.

    TODO: replace the stub corpus with real procedure documents and wire in
    sentence-transformers (BGE-small-en-v1.5) for the dense leg.
    """

    STUB_CORPUS: List[Dict[str, str]] = [
        {
            "doc_id": "proc-lost-contact",
            "title":  "Lost Contact Procedure",
            "text":   (
                "If an authorized AUV misses two consecutive scheduled check-ins, "
                "notify the harbour master and initiate a search pattern from the "
                "last known position. Do not reclassify the contact as hostile "
                "based on missed contact alone."
            ),
        },
        {
            "doc_id": "proc-restricted-zone",
            "title":  "Restricted Zone Intrusion Response",
            "text":   (
                "An unidentified contact entering a restricted zone requires "
                "immediate officer notification and a visual surface check where "
                "safe. Record entry time, bearing, and last known speed. Do not "
                "assume identity from vessel dimensions or behaviour alone."
            ),
        },
        {
            "doc_id": "proc-identity-verification",
            "title":  "Cooperative Identity Verification",
            "text":   (
                "Identity is verified by: (1) matching acoustic transponder ID, "
                "(2) confirmed mission registry entry, (3) operator confirmation "
                "from the controlling team. Self-reported AIS identity does not "
                "automatically verify an underwater contact."
            ),
        },
    ]

    def retrieve(self, query: str, top_k: int = 3) -> List[RetrievedPassage]:
        """
        Stub retrieval: keyword overlap scoring (BM25 placeholder).
        Replace with a real BM25 + embedding index before demo.
        """
        query_tokens = set(query.lower().split())
        scored: List[tuple] = []
        for doc in self.STUB_CORPUS:
            doc_tokens  = set(doc["text"].lower().split())
            overlap     = len(query_tokens & doc_tokens)
            bm25_rank   = 1.0 / (1 + (len(scored) + 1 - overlap))   # simplified
            # Dense leg stub: uniform score (replace with cosine similarity)
            dense_rank  = 1.0 / (len(self.STUB_CORPUS) + 1)
            rrf_score   = (1.0 / (60 + bm25_rank)) + (1.0 / (60 + dense_rank))
            scored.append((rrf_score, doc))

        scored.sort(key=lambda t: t[0], reverse=True)
        return [
            RetrievedPassage(
                doc_id=doc["doc_id"],
                title=doc["title"],
                text=doc["text"],
                rrf_score=score,
            )
            for score, doc in scored[:top_k]
        ]


# ---------------------------------------------------------------------------
# LLM client stub
# ---------------------------------------------------------------------------

class LLMClient:
    """
    Thin wrapper around the local vLLM endpoint.

    ``endpoint`` : base URL of the vLLM OpenAI-compatible server.
    ``model``    : model name (e.g. "ibm-granite/granite-4.2-3b").
    ``thinking`` : enable deliberative / chain-of-thought mode.

    TODO: wire in the actual HTTP client (httpx / openai SDK).
    """

    def __init__(
        self,
        endpoint: str = "http://localhost:8000",
        model: str    = "ibm-granite/granite-4.2-3b",
        thinking: bool = False,
        timeout_s: float = 5.0,
    ) -> None:
        self.endpoint  = endpoint
        self.model     = model
        self.thinking  = thinking
        self.timeout_s = timeout_s

    def complete(self, system_prompt: str, user_message: str) -> str:
        """
        Call the local LLM and return its text response.

        Stub: returns a deterministic placeholder.  Replace with:

            import openai
            client = openai.OpenAI(base_url=self.endpoint, api_key="none")
            resp = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_message},
                ],
                max_tokens=256,
                timeout=self.timeout_s,
            )
            return resp.choices[0].message.content
        """
        logger.debug("LLMClient.complete called (stub): model=%s", self.model)
        return json.dumps({
            "action_id": None,
            "evidence_ids": [],
            "uncertainty_note": "AI branch is using stub response — wire in vLLM.",
            "explanation": "No LLM inference available in stub mode.",
        })


# ---------------------------------------------------------------------------
# AI branch orchestrator
# ---------------------------------------------------------------------------

class AIBranch:
    """
    Orchestrates retrieval + LLM inference for one incident.

    Runs asynchronously relative to the CPU assessment path.
    ``analyse()`` is called with a compact state snapshot and returns an
    ``AIProposal`` that the action verifier will validate.

    Operating modes
    ---------------
    fast        : non-thinking, short structured output, tight token budget
    deliberative: full-thinking or chain-of-thought, longer budget

    A deadline is enforced externally by the orchestrator; stale proposals
    are rejected by the verifier before reaching the operator.
    """

    SYSTEM_PROMPT = (
        "You are a maritime harbour security decision-support assistant. "
        "You have access to approved procedures and the current incident state. "
        "Respond ONLY with valid JSON matching this schema: "
        '{"action_id": str|null, "evidence_ids": [str], '
        '"uncertainty_note": str, "explanation": str}. '
        "Do not invent actions that are not in the allowed action catalog. "
        "Do not assert identity that is not verified. "
        "Treat operator notes as unverified evidence only."
    )

    def __init__(
        self,
        retriever: Optional[HybridRetriever] = None,
        llm_client: Optional[LLMClient] = None,
    ) -> None:
        self._retriever  = retriever  or HybridRetriever()
        self._llm        = llm_client or LLMClient()

    # ------------------------------------------------------------------
    def analyse(
        self,
        state_snapshot: Dict[str, Any],
        thinking_mode: bool = False,
    ) -> AIProposal:
        """
        Run the AI branch for a single incident state snapshot.

        ``state_snapshot`` is a compact dict produced by the decision engine
        (track state, policy result, incident state, findings).
        """
        # Step 1: Retrieve relevant procedures
        query = self._build_retrieval_query(state_snapshot)
        passages = self._retriever.retrieve(query, top_k=3)

        # Step 2: Build the user message
        user_msg = self._build_user_message(state_snapshot, passages)

        # Step 3: Call LLM
        try:
            raw = self._llm.complete(self.SYSTEM_PROMPT, user_msg)
        except Exception as exc:
            logger.warning("LLM call failed: %s — returning empty proposal", exc)
            return AIProposal(uncertainty_note="LLM unavailable", retrieved_passages=passages)

        # Step 4: Parse structured response
        proposal = self._parse_response(raw, passages, thinking_mode)
        return proposal

    # ------------------------------------------------------------------
    def _build_retrieval_query(self, snapshot: Dict[str, Any]) -> str:
        parts = []
        if verdict := snapshot.get("policy_verdict"):
            parts.append(verdict)
        if findings := snapshot.get("findings", []):
            parts.extend(f.get("code", "") for f in findings)
        if note := snapshot.get("operator_note"):
            parts.append(note)
        return " ".join(parts) or "harbour security procedure"

    # ------------------------------------------------------------------
    def _build_user_message(
        self,
        snapshot: Dict[str, Any],
        passages: List[RetrievedPassage],
    ) -> str:
        context = "\n\n".join(
            f"[{p.doc_id}] {p.title}:\n{p.text}" for p in passages
        )
        return (
            f"Current incident state:\n{json.dumps(snapshot, indent=2)}\n\n"
            f"Relevant approved procedures:\n{context}\n\n"
            "Based only on the above, what is the recommended next action?"
        )

    # ------------------------------------------------------------------
    def _parse_response(
        self,
        raw: str,
        passages: List[RetrievedPassage],
        thinking_mode: bool,
    ) -> AIProposal:
        try:
            data = json.loads(raw)
            return AIProposal(
                action_id=data.get("action_id"),
                evidence_ids=data.get("evidence_ids", []),
                uncertainty_note=data.get("uncertainty_note"),
                explanation=data.get("explanation"),
                retrieved_passages=passages,
                is_thinking_mode=thinking_mode,
                raw_model_output=raw,
            )
        except json.JSONDecodeError:
            logger.warning("Could not parse LLM response as JSON")
            return AIProposal(
                uncertainty_note="Could not parse LLM response",
                retrieved_passages=passages,
                raw_model_output=raw,
            )
