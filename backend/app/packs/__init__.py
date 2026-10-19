"""Content packs (Phase F1): versioned bundles of checklists and rules, held as data.

A pack is a JSON manifest under ``app/packs/data/``. Shipped packs are synthetic
drafts: they must carry the synthetic disclaimer, may not present themselves as
external regulatory requirements, and their rules carry open questions (TODO) so
they stay unverified. Installing a pack copies its checklists and rules into an
organisation as **draft** versions that people then review, edit, verify and
publish. The manifest's SHA-256 is recorded so an install is traceable to the exact
file it came from.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.engine.versions import parse_check
from app.models import DatasetKind
from app.schemas import RequirementIn, RuleIn

DATA = Path(__file__).parent / "data"
SYNTHETIC_DISCLAIMER = "Synthetic demonstration content — not legal guidance."
PackId = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,59}$")


class PackError(ValueError):
    pass


class PackChecklist(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    requirements: list[RequirementIn] = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def _requirements(self) -> PackChecklist:
        codes = [r.code for r in self.requirements]
        if len(codes) != len(set(codes)):
            raise ValueError(f"{self.name}: requirement codes must be unique")
        for r in self.requirements:
            if r.source_id is not None:
                raise ValueError(f"{r.code}: packs cannot reference an organisation's sources")
            try:
                parse_check(r.check_config)
            except ValidationError as exc:
                raise ValueError(f"{r.code}: invalid check configuration") from exc
        return self


class PackRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prefix: str = Field(pattern=r"^[a-z0-9]+(?:\.[a-z0-9_]+)*$", max_length=80)
    rules: list[RuleIn] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _keys(self) -> PackRules:
        for r in self.rules:
            if not r.rule_key.startswith(f"{self.prefix}."):
                raise ValueError(f"{r.rule_key}: rule keys must start with {self.prefix}.")
            if not r.todo:
                raise ValueError(f"{r.rule_key}: a shipped rule needs an open question (todo)")
        return self


class PackManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = PackId
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    title: str = Field(min_length=1, max_length=200)
    sector: Literal[
        "financial_services",
        "banking",
        "insurance",
        "listed_companies",
        "sustainability",
        "corporate",
    ]
    jurisdiction: Literal["generic"] = "generic"
    status: Literal["draft"] = "draft"
    synthetic: Literal[True] = True
    disclaimer: str
    description: str = Field(max_length=5000)
    dataset_kinds: list[DatasetKind] = Field(default_factory=list, max_length=20)
    open_questions: list[str] = Field(min_length=1, max_length=50)
    checklists: list[PackChecklist] = Field(min_length=1, max_length=20)
    rules: PackRules | None = None

    @model_validator(mode="after")
    def _disclaimer(self) -> PackManifest:
        if self.disclaimer != SYNTHETIC_DISCLAIMER:
            raise ValueError("synthetic packs must carry the synthetic disclaimer verbatim")
        return self


@dataclass(frozen=True)
class Pack:
    manifest: PackManifest
    sha256: str


def load(raw: bytes) -> Pack:
    try:
        manifest = PackManifest.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as exc:
        raise PackError(str(exc)[:500]) from exc
    return Pack(manifest, hashlib.sha256(raw).hexdigest())


@lru_cache
def catalog() -> dict[str, Pack]:
    packs: dict[str, Pack] = {}
    for path in sorted(DATA.glob("*.json")):
        pack = load(path.read_bytes())
        if pack.manifest.id in packs:
            raise PackError(f"duplicate pack id {pack.manifest.id}")
        packs[pack.manifest.id] = pack
    return packs
