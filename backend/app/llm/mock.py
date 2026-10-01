"""Deterministic MOCK provider for demo mode. This is keyword matching, NOT AI evaluation.

Every result it produces is labelled is_mock=True in the database, API and UI.
"""
import re
from decimal import ROUND_HALF_UP, Decimal

from app.llm.base import (
    CriterionResult,
    CriterionSpec,
    EvidenceItem,
    LLMProvider,
    ProposedCriterion,
    parse_term,
)
from app.parsing import Segment

# (label, synonyms) used by the mock to turn job-description bullets into evidence terms.
VOCAB: list[tuple[str, list[str]]] = [
    ("Python", ["python"]),
    ("PyTorch", ["pytorch"]),
    ("TensorFlow", ["tensorflow"]),
    ("LLMs", ["llm", "llms", "large language model"]),
    ("RAG", ["rag", "retrieval-augmented generation", "retrieval augmented generation"]),
    ("Vector search", ["vector search", "vector database", "vector store"]),
    ("SQL", ["sql", "postgresql", "mysql"]),
    ("Docker", ["docker"]),
    ("Kubernetes", ["kubernetes", "k8s"]),
    ("Machine learning", ["machine learning", "ml"]),
    ("Deployment", ["deploy"]),
    ("Production systems", ["production"]),
    ("AWS", ["aws", "amazon web services"]),
    ("Azure", ["azure"]),
    ("Google Cloud", ["google cloud", "gcp"]),
    ("Prompt design", ["prompt"]),
    ("Evaluation", ["evaluat"]),
    ("Benchmarks", ["benchmark", "evaluation dataset"]),
    ("REST APIs", ["rest api", "fastapi", "flask"]),
    ("Monitoring", ["monitor"]),
    ("Model drift", ["drift"]),
    ("Collaboration", ["collaborat", "cross-functional"]),
    ("End-to-end delivery", ["end-to-end"]),
    ("Certification", ["certif"]),
    ("Git", ["git", "github", "gitlab"]),
    ("CI/CD", ["ci/cd", "continuous integration", "github actions", "jenkins"]),
    ("Automated testing", ["automated test", "unit test", "pytest", "integration test"]),
    ("Statistics", ["statistic"]),
    ("Data visualization", ["visualization", "tableau", "power bi"]),
    ("Spark", ["spark", "databricks"]),
    # general software delivery
    ("Project planning", ["project plan", "planning", "roadmap", "project ideas"]),
    ("Merge conflicts", ["merge conflict", "merge"]),
    ("Business requirements", ["business requirement"]),
    ("Code quality", ["code quality", "quality standard"]),
    ("Leadership", ["led", "lead", "leading", "leadership", "managed", "managing", "manager", "manage the", "manage a", "mentor"]),
    ("Client engagement", ["client", "stakeholder"]),
    ("Documentation", ["documentation", "documented", "document new"]),
    ("Code review", ["code review", "peer review"]),
    ("Software development", ["software develop", "software engineer"]),
    ("Master's degree", ["master", "m.s.", "msc", "m.sc"]),
    # marketing
    ("Marketing strategy", ["marketing strateg", "go-to-market"]),
    ("Freelancing / marketplace", ["freelanc", "gig economy", "marketplace"]),
    ("Campaigns", ["campaign"]),
    ("Content marketing", ["content"]),
    ("Social media", ["social media"]),
    ("Customer acquisition", ["acquisition"]),
    ("SEO/SEM", ["seo", "sem", "search engine"]),
    ("Paid media", ["paid media", "paid social", "ppc"]),
    ("Analytics", ["analy", "data-driven"]),
    ("Community building", ["communit"]),
    ("Growth", ["growth", "scaled", "scaling"]),
    ("Performance marketing", ["performance marketing"]),
    ("CRM", ["crm", "hubspot", "salesforce"]),
    ("Communication", ["communicat", "present"]),
]

CATEGORY_RULES: list[tuple[str, str, str]] = [
    # (regex on heading, category, criterion name)
    (r"qualif|certif", "qualifications", ""),
    (r"skill", "skills", "Relevant technical skills"),
    (r"experience", "experience", "Relevant professional experience"),
    (r"responsib|duties|what you will do", "responsibilities", "Role responsibilities"),
    (r"project", "projects", "Relevant project evidence"),
]
BASE_WEIGHTS = {"skills": 30, "experience": 25, "responsibilities": 20, "projects": 15, "qualifications": 10}

LEVEL_THRESHOLDS = [(0.8, "strong"), (0.6, "substantial"), (0.3, "partial")]
# Sections not used as evidence (contact details / personal data).
EXCLUDED_SECTIONS = {"header", "personal"}


def _pattern_regex(p: str) -> re.Pattern:
    p = p.lower()
    # Short tokens (sql, aws, ml, git) need an end boundary; longer ones are stems ("deploy" -> "deployed").
    tail = r"\b" if len(p) <= 4 else ""
    return re.compile(r"(?<![\w])" + re.escape(p) + tail, re.IGNORECASE)


def _matches(patterns: list[str], text: str) -> bool:
    return any(_pattern_regex(p).search(text) for p in patterns)


def _first_pos(patterns: list[str], text: str) -> int:
    return min((m.start() for p in patterns if (m := _pattern_regex(p).search(text))), default=-1)


def _terms_for_bullet(bullet: str) -> list[str]:
    hits = [(label, syns, _first_pos(syns, bullet)) for label, syns in VOCAB if _matches(syns, bullet)]
    if not hits:
        return []
    # "PyTorch or TensorFlow", "AWS, Azure, or Google Cloud": terms close to an "or" are alternatives.
    groups: list[list[tuple[str, list[str], int]]] = []
    merged: set[str] = set()
    for m in re.finditer(r"\bor\b", bullet, re.IGNORECASE):
        near = [h for h in hits if abs(h[2] - m.start()) <= 35 and h[0] not in merged]
        if len(near) > 1:
            groups.append(near)
            merged.update(h[0] for h in near)
    out: list[str] = []
    for label, syns, _ in hits:
        if label in merged:
            g = next(g for g in groups if g[0][0] == label) if any(g[0][0] == label for g in groups) else None
            if g:
                out.append(f"{' / '.join(h[0] for h in g)}: {'|'.join(s for h in g for s in h[1])}")
            continue
        out.append(f"{label}: {'|'.join(syns)}")
    return out


def _split_sections(jd: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    heading = None
    bullets: list[str] = []
    for raw in jd.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^[-*•]\s*(.+)$", line)
        if m:
            bullets.append(m.group(1).strip())
        else:
            if heading is not None and bullets:
                sections.append((heading, bullets))
            heading, bullets = line.rstrip(":"), []
    if heading is not None and bullets:
        sections.append((heading, bullets))
    return sections


def normalize_weights(raw: list[Decimal]) -> list[Decimal]:
    total = sum(raw)
    if total <= 0:
        return raw
    scaled = [(r * 100 / total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) for r in raw]
    diff = Decimal(100) - sum(scaled)
    scaled[scaled.index(max(scaled))] += diff
    return scaled


class MockLLMProvider(LLMProvider):
    name = "mock"
    model = "mock-keyword-matcher-v1"
    prompt_version = "mock-v1"
    is_mock = True

    def propose_rubric(self, job_description: str) -> list[ProposedCriterion]:
        proposals: list[tuple[ProposedCriterion, Decimal]] = []
        seen_categories: set[str] = set()
        for heading, bullets in _split_sections(job_description):
            rule = next(((cat, name) for rx, cat, name in CATEGORY_RULES if re.search(rx, heading, re.I)), None)
            if rule is None:
                continue
            category, name = rule
            required = bool(re.search(r"\b(required|must|mandatory)\b", heading, re.I))
            if category == "qualifications":
                # Each explicit qualification becomes its own criterion so it can be tracked as required.
                share = Decimal(BASE_WEIGHTS[category]) / len(bullets)
                for b in bullets:
                    terms = _terms_for_bullet(b) or [b[:60]]
                    proposals.append(
                        (ProposedCriterion(b[:120], category, b, 0, required, terms), share)
                    )
            elif category not in seen_categories:
                terms: list[str] = []
                for b in bullets:
                    for t in _terms_for_bullet(b):
                        if t not in terms:
                            terms.append(t)
                proposals.append(
                    (
                        ProposedCriterion(name, category, "; ".join(bullets), 0, required, terms),
                        Decimal(BASE_WEIGHTS[category]),
                    )
                )
            seen_categories.add(category)

        if not proposals:
            terms = []
            for b in job_description.splitlines():
                for t in _terms_for_bullet(b):
                    if t not in terms:
                        terms.append(t)
            proposals = [
                (
                    ProposedCriterion(
                        "Overall role alignment", "general",
                        "No structured sections were found in the job description; edit this rubric.",
                        0, False, terms,
                    ),
                    Decimal(100),
                )
            ]
        weights = normalize_weights([w for _, w in proposals])
        for (p, _), w in zip(proposals, weights):
            p.weight = float(w)
        return [p for p, _ in proposals]

    def assess(self, criteria: list[CriterionSpec], segments: list[Segment]) -> list[CriterionResult]:
        usable = [s for s in segments if s.section not in EXCLUDED_SECTIONS]
        results: list[CriterionResult] = []
        for c in criteria:
            evidence: list[EvidenceItem] = []
            supported: list[str] = []
            missing: list[str] = []
            ambiguities: list[str] = []
            used_segments: set[int] = set()
            terms = [parse_term(t) for t in c.evidence_terms]
            for label, patterns in terms:
                hits = [s for s in usable if _matches(patterns, s.text)]
                if not hits:
                    missing.append(label)
                    continue
                supported.append(label)
                contextual = [s for s in hits if s.section != "skills"]
                best = (contextual or hits)[0]
                if not contextual:
                    ambiguities.append(
                        f"'{label}' appears only in a skills list; no work or project context was found."
                    )
                if best.index not in used_segments:
                    used_segments.add(best.index)
                    evidence.append(
                        EvidenceItem(quote=best.text[:240], page=best.page, section=best.section,
                                     segment_index=best.index, term=label)
                    )
            coverage = len(supported) / len(terms) if terms else 0.0
            level = next((lvl for th, lvl in LEVEL_THRESHOLDS if coverage >= th), "limited" if coverage > 0 else "none")
            results.append(
                CriterionResult(
                    criterion_id=c.id,
                    level=level,
                    evidence=evidence,
                    supported_points=supported,
                    missing=missing,
                    ambiguities=ambiguities,
                    rationale=(
                        f"MOCK keyword matcher: found {len(supported)} of {len(terms)} rubric evidence terms "
                        f"({coverage:.0%}) -> level '{level}'. Not an AI judgement."
                    ),
                )
            )
        return results
