from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from app.engine import DocumentContext, evaluate, parse_config
from app.engine.patterns import PatternError, compile_pattern
from app.models import CheckOutcome


@dataclass
class Block:
    text: str
    ref: str = "para-1"
    page_number: int | None = None
    paragraph_number: int | None = 1
    id: uuid.UUID = uuid.uuid4()


def ctx(*texts: str, **meta: object) -> DocumentContext:
    blocks = [
        Block(t, ref=f"para-{i}", paragraph_number=i, id=uuid.uuid4())
        for i, t in enumerate(texts, 1)
    ]
    return DocumentContext(
        title=str(meta.get("title", "T")),
        description="",
        document_type=str(meta.get("document_type", "policy")),
        tags=list(meta.get("tags", [])),
        blocks=blocks,
    )  # type: ignore[call-overload]


def run(config: dict, doc: DocumentContext):  # type: ignore[no-untyped-def,type-arg]
    return evaluate(parse_config(config), doc)


def test_required_text_any_and_all() -> None:
    doc = ctx("The Policy  Owner is the CISO.", "Data retention applies.")
    r = run({"type": "required_text", "phrases": ["policy owner"]}, doc)
    assert r.outcome == CheckOutcome.MATCH_FOUND and not r.needs_attention
    ev = r.evidence[0]
    assert ev["ref"] == "para-1" and ev["quote"] == "Policy Owner"
    assert ev["context"][ev["highlight_start"] : ev["highlight_end"]] == "Policy Owner"
    r = run({"type": "required_text", "phrases": ["policy owner", "approval"], "match": "all"}, doc)
    assert r.outcome == CheckOutcome.NO_MATCH_FOUND and r.needs_attention
    assert "approval" in r.message


def test_case_sensitive_option() -> None:
    doc = ctx("policy owner")
    r = run({"type": "required_text", "phrases": ["Policy Owner"], "case_sensitive": True}, doc)
    assert r.outcome == CheckOutcome.NO_MATCH_FOUND


def test_phrase_groups() -> None:
    doc = ctx("Incidents must be reported promptly.")
    ok = run({"type": "phrase_groups", "groups": [["incident"], ["notify", "reported"]]}, doc)
    assert ok.outcome == CheckOutcome.MATCH_FOUND
    bad = run({"type": "phrase_groups", "groups": [["incident"], ["within 72 hours"]]}, doc)
    assert bad.outcome == CheckOutcome.NO_MATCH_FOUND and "group(s) 2" in bad.message


def test_prohibited_terms_flags_matches() -> None:
    doc = ctx("Our systems are 100% secure.")
    r = run({"type": "prohibited_terms", "terms": ["100% secure"]}, doc)
    assert r.outcome == CheckOutcome.MATCH_FOUND and r.needs_attention
    clean = run({"type": "prohibited_terms", "terms": ["guaranteed"]}, doc)
    assert clean.outcome == CheckOutcome.NO_MATCH_FOUND and not clean.needs_attention


def test_pattern_placeholders() -> None:
    doc = ctx("Effective date: 01/03/2026. Limit is 30 days.")
    assert (
        run({"type": "pattern", "pattern": "effective date {any} {date}"}, doc).outcome
        == CheckOutcome.MATCH_FOUND
    )
    assert (
        run({"type": "pattern", "pattern": "within {number} days"}, doc).outcome
        == CheckOutcome.NO_MATCH_FOUND
    )
    absent = run({"type": "pattern", "pattern": "is {number} days", "expect": "absent"}, doc)
    assert absent.outcome == CheckOutcome.MATCH_FOUND and absent.needs_attention


def test_pattern_syntax_is_literal_not_regex() -> None:
    rx = compile_pattern("a.b (c)+ [x]")
    assert rx.search("a.b (c)+ [x]") and not rx.search("aXb ccc x")


def test_pattern_rejects_bad_input() -> None:
    with pytest.raises(PatternError):
        compile_pattern("")
    with pytest.raises(PatternError):
        compile_pattern("x" * 201)
    with pytest.raises(PatternError):
        compile_pattern(" ".join(["{any}"] * 7))


def test_pattern_matching_is_bounded_on_hostile_input() -> None:
    rx = compile_pattern("{any} {any} {any} {any} {any} zzz")
    hostile = "a " * 20000
    start = time.perf_counter()
    assert rx.search(hostile) is None
    assert time.perf_counter() - start < 2.0


def test_metadata_checks() -> None:
    doc = ctx("x", document_type="contract", tags=["vendor"])
    assert (
        run({"type": "metadata", "field": "document_type", "equals": "policy"}, doc).outcome
        == CheckOutcome.NO_MATCH_FOUND
    )
    assert (
        run({"type": "metadata", "field": "tags", "equals": "VENDOR"}, doc).outcome
        == CheckOutcome.MATCH_FOUND
    )


def test_manual_requires_human() -> None:
    r = run({"type": "manual"}, ctx("x"))
    assert r.outcome == CheckOutcome.NEEDS_HUMAN_REVIEW and r.needs_attention


@pytest.mark.parametrize(
    "config",
    [
        {"type": "regex", "pattern": ".*"},
        {"type": "required_text", "phrases": []},
        {"type": "required_text", "phrases": ["x"], "code": "import os"},
        {"type": "required_text", "phrases": ["x" * 201]},
        {"type": "prohibited_terms", "terms": ["t"] * 26},
        {"type": "pattern", "pattern": "(a+)+$"},  # compiles as literal but is fine; length ok
        {"type": "metadata", "field": "password"},
    ],
)
def test_config_validation(config: dict) -> None:  # type: ignore[type-arg]
    if config.get("pattern") == "(a+)+$":
        # Accepted, but only as literal text: no catastrophic regex is built.
        parsed = parse_config(config)
        assert evaluate(parsed, ctx("aaaa" * 1000 + "!")).outcome == CheckOutcome.NO_MATCH_FOUND
        return
    with pytest.raises(ValidationError):
        parse_config(config)


def test_arabic_text_matching() -> None:
    doc = ctx("مالك السياسة: رئيس أمن المعلومات")
    r = run({"type": "required_text", "phrases": ["مالك السياسة"]}, doc)
    assert r.outcome == CheckOutcome.MATCH_FOUND
