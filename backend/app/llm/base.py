"""Provider-neutral LLM interface.

The LLM's job is limited to (1) proposing rubric criteria for recruiter review and
(2) extracting evidence + assigning a discrete level per criterion. It never computes the
final score; app.scoring does that deterministically.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.parsing import Segment

LEVELS = ("strong", "substantial", "partial", "limited", "none")


@dataclass
class ProposedCriterion:
    name: str
    category: str
    description: str
    weight: float
    required: bool
    evidence_terms: list[str]


@dataclass
class CriterionSpec:
    id: str
    name: str
    category: str
    description: str
    required: bool
    evidence_terms: list[str]


@dataclass
class EvidenceItem:
    quote: str
    page: int | None = None
    section: str | None = None
    segment_index: int | None = None
    term: str | None = None


@dataclass
class CriterionResult:
    criterion_id: str
    level: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    supported_points: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)
    rationale: str = ""


class LLMProvider(ABC):
    name: str
    model: str
    prompt_version: str
    is_mock: bool

    @abstractmethod
    def propose_rubric(self, job_description: str) -> list[ProposedCriterion]: ...

    @abstractmethod
    def assess(self, criteria: list[CriterionSpec], segments: list[Segment]) -> list[CriterionResult]: ...

    def config(self) -> dict:
        return {
            "provider": self.name,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "is_mock": self.is_mock,
        }


def parse_term(term: str) -> tuple[str, list[str]]:
    """'Label: a|b' -> ('Label', ['a','b']); 'a|b' -> ('a / b', ['a','b'])."""
    term = term.strip()
    if ":" in term:
        label, _, alts = term.partition(":")
        patterns = [p.strip() for p in alts.split("|") if p.strip()]
        label = label.strip()
        if patterns and label:
            return label, patterns
    patterns = [p.strip() for p in term.split("|") if p.strip()]
    return " / ".join(patterns), patterns
