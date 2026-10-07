"""The shape a coaching guide must have. The model is asked for JSON matching it (JSON mode),
and every reply is validated here: providers can still return malformed or off-schema output."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Focus = Literal["cache", "model_mix", "discipline"]


class CoachingAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=80, description="Short imperative title")
    problem: str = Field(min_length=10, max_length=400, description="What the data shows, citing FACTS numbers")
    fix: str = Field(min_length=10, max_length=400, description="A concrete change to make")
    focus: Focus = Field(description="The score area this action improves")


class CoachingGuide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(min_length=5, max_length=160)
    actions: list[CoachingAction] = Field(min_length=1, max_length=5)


def _inline_refs(schema):
    """Pydantic emits nested models as $defs/$ref; send the model one self-contained schema."""
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(dict(defs[node["$ref"].split("/")[-1]]))
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


GUIDE_JSON_SCHEMA = _inline_refs(CoachingGuide.model_json_schema())


# ── Team memo (UPG-08) ──────────────────────────────────────────────────────

class TeamFocus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area: Focus = Field(description="The score area the team should work on")
    why: str = Field(min_length=10, max_length=300, description="Why, citing FACTS numbers")
    practice: str = Field(min_length=10, max_length=300, description="A concrete team practice")


class TeamMemo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=20, max_length=600, description="How the team is doing, from FACTS")
    focus: list[TeamFocus] = Field(min_length=1, max_length=2)


TEAM_MEMO_JSON_SCHEMA = _inline_refs(TeamMemo.model_json_schema())
