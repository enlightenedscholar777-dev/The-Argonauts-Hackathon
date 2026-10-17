import json
import re

from pydantic import Field
from rank_bm25 import BM25Okapi

from .schemas import ID, Strict


class Procedure(Strict):
    procedure_id: ID
    version: ID
    title: str = Field(max_length=120)
    applicable_reason_codes: list[ID]
    allowed_actions: list[ID]
    text: str = Field(max_length=1200)
    authority: str = Field(pattern="^demo-authored$")


def load_procedures(path, version):
    with open(path, encoding="utf-8") as file:
        records = [Procedure.model_validate(p).model_dump() for p in json.load(file)]
    if not 8 <= len(records) <= 12 or len({p["procedure_id"] for p in records}) != len(records):
        raise ValueError("Provide 8–12 uniquely identified demo procedures")
    if any(p["version"] != version for p in records):
        raise ValueError("Procedure version must match pinned policy")
    return records


def retrieve(records, assessment, version):
    reasons = set(assessment["risk"]["reason_codes"])
    action = assessment["recommendation"]["primary_action"]
    eligible = [
        p
        for p in records
        if p["version"] == version
        and action in p["allowed_actions"]
        and reasons.intersection(p["applicable_reason_codes"])
    ]
    if not eligible:
        return []

    def tokenize(text):
        return re.findall(r"[a-z0-9]+", text.lower())

    corpus = [tokenize(p["title"] + " " + p["text"]) for p in eligible]
    if not all(corpus):
        return eligible[:3]  # Explicit reason/action matches remain valid without searchable tokens.
    scores = BM25Okapi(corpus).get_scores(tokenize(" ".join(sorted(reasons)) + " " + action))
    return [p for _, p in sorted(zip(scores, eligible), key=lambda v: (-v[0], v[1]["procedure_id"]))[:3]]
