"""Untrusted-content handling.

Resumes and job descriptions are DATA, never instructions. This module:
  * detects instruction-like text embedded in resumes (prompt injection) and removes it from
    model input, recording a flag for recruiter review;
  * redacts direct identifiers and protected-characteristic text before model assessment;
  * rejects rubric criteria that reference protected characteristics or school prestige.
Detection is heuristic. The stronger guarantees are structural: the score is computed in
application code, model output is schema-validated, and cited evidence must exist in the document.
"""
import re

from app.parsing import Segment

_INJECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    (label, re.compile(rx, re.IGNORECASE))
    for label, rx in [
        ("override-instructions", r"\b(ignore|disregard|forget|override)\b[^.]{0,40}\b(previous|prior|above|earlier|all|any)\b[^.]{0,20}\b(instructions?|prompts?|rules|guidelines|directions)"),
        ("system-prompt-reference", r"\b(system|developer)\s+(prompt|message|instructions?)\b"),
        ("role-reassignment", r"\byou\s+are\s+(now\s+)?(an?\s+|the\s+)?(ai|assistant|language model|chatbot|screener|recruiter|evaluator|model)\b"),
        ("score-manipulation", r"\b(give|assign|award|rate|score|rank|mark)\b[^.]{0,40}\b(score|rating|rank(ing)?)\s+(of\s+)?\d{2,3}\b"),
        ("score-manipulation", r"\b(score|rate|rank)\s+(this|me|my)\b[^.]{0,30}\b(100|highest|top|perfect|maximum)\b"),
        ("addressed-to-ai", r"\b(note|message|instruction)s?\s+(to|for)\s+(the\s+)?(ai|llm|model|screening system|ats|recruit\w* (bot|system|ai))\b"),
        ("markup-injection", r"<\s*/?\s*(system|assistant|instructions?|prompt|im_start|im_end)\s*>"),
        ("new-instructions", r"\b(new|updated|additional)\s+instructions?\s*:"),
        ("do-not-evaluate", r"\bdo\s+not\s+(evaluate|assess|score|penali[sz]e)\b"),
    ]
]


def find_injection(text: str) -> str | None:
    for label, rx in _INJECTION_PATTERNS:
        if rx.search(text):
            return label
    return None


def screen_segments(segments: list[Segment]) -> tuple[list[Segment], list[dict]]:
    """Return (clean segments, flagged details). Wrapped continuation lines of a flagged
    sentence (previous line ends mid-sentence with , ; : - or next line starts lowercase) are
    flagged too, so keywords in the wrapped tail do not leak into scoring."""
    flagged_idx: dict[int, str] = {}
    for i, seg in enumerate(segments):
        label = find_injection(seg.text)
        if label:
            flagged_idx[i] = label
            j = i
            while (
                j + 1 < len(segments)
                and (re.search(r"[,;:\-]\s*$", segments[j].text) or re.match(r"[a-z]", segments[j + 1].text))
                and segments[j + 1].page == segments[j].page
                and segments[j + 1].section == segments[j].section
            ):
                j += 1
                flagged_idx.setdefault(j, "continuation-of-flagged-text")
    clean = [s for i, s in enumerate(segments) if i not in flagged_idx]
    details = [
        {
            "type": "prompt_injection_suspected",
            "pattern": label,
            "page": segments[i].page,
            "section": segments[i].section,
            "excerpt": segments[i].text[:160],
        }
        for i, label in sorted(flagged_idx.items())
    ]
    return clean, details


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_URL_RE = re.compile(r"\b(https?://\S+|www\.\S+|[\w-]+\.(com|io|net|org|dev|me)/\S*)", re.IGNORECASE)
_PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
_DOB_RE = re.compile(r"\b(date of birth|d\.?o\.?b\.?|born(\s+on|\s+in)?)\b[:\s]*[\w ,/.-]{0,30}", re.IGNORECASE)
_AGE_RE = re.compile(r"\b(age[:\s]+\d{1,2}|\d{2}\s*(years old|yrs old|y/o))\b", re.IGNORECASE)
_SENSITIVE_RE = re.compile(
    r"\b(male|female|gender|pronouns?|married|divorced|widowed|marital status|religion|religious|"
    r"nationality|citizenship|ethnicity|race|pregnan\w*|disabilit\w*|veteran status)\b",
    re.IGNORECASE,
)


def _phone_sub(m: re.Match) -> str:
    raw = m.group(0)
    digits = sum(c.isdigit() for c in raw)
    if digits < 8 or re.fullmatch(r"\(?\d{4}\s*[-/]\s*\d{4}\)?", raw.strip()):
        return raw  # date ranges such as "2018 - 2021" are not phone numbers
    return "[PHONE]"


def redact_text(text: str, names: list[str] | None = None) -> str:
    out = _EMAIL_RE.sub("[EMAIL]", text)
    out = _URL_RE.sub("[LINK]", out)
    out = _DOB_RE.sub("[REDACTED]", out)
    out = _AGE_RE.sub("[REDACTED]", out)
    out = _PHONE_RE.sub(_phone_sub, out)
    out = _SENSITIVE_RE.sub("[REDACTED]", out)
    for name in names or []:
        for part in {name, *name.split()}:
            if len(part) >= 3:
                out = re.sub(rf"\b{re.escape(part)}\b", "[CANDIDATE]", out, flags=re.IGNORECASE)
    return out


def redact_segments(segments: list[Segment], names: list[str] | None = None) -> list[Segment]:
    return [Segment(s.index, s.page, s.section, redact_text(s.text, names)) for s in segments]


_PROHIBITED_CRITERIA_RE = re.compile(
    r"\b(age|aged|young|youthful|years? old|recent grad(uate)?s?|digital native|"
    r"gender|male|female|man|woman|racial|ethnic\w*|religio\w*|nationality|national origin|"
    r"native (english )?speaker|citizenship|marital|married|pregnan\w*|disabilit\w*|"
    r"photo(graph)?s?|appearance|attractive|"
    r"ivy league|top[- ]tier (school|university|college)|prestigious|elite (school|university|college)|"
    r"top \d+ (school|university|college))\b",
    re.IGNORECASE,
)


def prohibited_criterion_terms(*texts: str) -> list[str]:
    found: list[str] = []
    for t in texts:
        for m in _PROHIBITED_CRITERIA_RE.finditer(t or ""):
            found.append(m.group(0).lower())
    return sorted(set(found))


def neutralize_delimiters(text: str) -> str:
    """Prevent document text from closing or forging the prompt's data block."""
    return re.sub(r"</?\s*(untrusted_[a-z_]+|system|assistant|instructions?)\s*>", "[removed-tag]", text, flags=re.IGNORECASE)
