"""Check-face evidence and suggested marks in normalized, displayed page coordinates."""

from __future__ import annotations

from dataclasses import dataclass, field
import re


@dataclass(frozen=True)
class Box:
    left: float
    top: float
    right: float
    bottom: float

    def padded(self, x: float, above: float, below: float) -> Box:
        return Box(max(0, self.left - x), max(0, self.top - above),
                   min(1, self.right + x), min(1, self.bottom + below))


@dataclass(frozen=True)
class Line:
    text: str
    box: Box


@dataclass(frozen=True)
class Mark:
    page: int
    kind: str
    box: Box


@dataclass
class Finding:
    status: str = "Unrelated"
    marks: list[Mark] = field(default_factory=list)
    issuer: str = ""
    number: str = ""


NEEDS_REVIEW = "Needs Review"
MICR_SYMBOLS = "⑆⑇⑈⑉"
NUMBER_LABEL = re.compile(r"\b(?:check|cheque)\s*(?:number|no\.?|#)?\s*[:#]?\s*(\d{2,12})\b", re.I)
ISSUER_SUFFIX = re.compile(r"\b(?:incorporated|inc|llc|ltd|corp(?:oration)?|company|association|foundation|university)\b", re.I)
PAYEE_LABEL = re.compile(r"\bpay\s+to(?:\s+the)?\s+order(?:\s+of)?\b", re.I)


def _routing(group: str) -> bool:
    if len(group) != 9 or len(set(group)) == 1:
        return False
    return sum(int(digit) * weight for digit, weight in zip(group, (3, 7, 1) * 3)) % 10 == 0


def _micr_strength(text: str) -> int:
    groups = re.findall(r"[0-9]+", text)
    digits = sum(map(len, groups))
    symbols = sum(text.count(symbol) for symbol in MICR_SYMBOLS)
    if symbols >= 2 and digits >= 8:
        return 2
    # OCR can drop or substitute E-13B separators. A routing checksum alone
    # would also match numbers printed on remittance instructions.
    if re.search(r"[a-zA-Z]{3}|[$%/]", text):
        return 0
    if digits >= 14 and any(_routing(group) for group in groups) and len(groups) >= 2:
        return 2
    return int((symbols > 0 and digits >= 6) or
               (digits >= 14 and (len(groups) >= 2 or digits >= 18)))


def _numeric_rows(lines: list[Line]) -> list[Line]:
    """Join OCR fragments of one printed band using their baseline and proximity."""
    fragments = [line for line in lines if re.search(r"[0-9⑆⑇⑈⑉]", line.text)
                 and not re.search(r"[a-zA-Z]{3}", line.text)]
    rows: list[list[Line]] = []
    for line in sorted(fragments, key=lambda item: item.box.left):
        for row in rows:
            last = row[-1].box
            overlap = min(last.bottom, line.box.bottom) - max(last.top, line.box.top)
            if (overlap > .5 * min(last.bottom - last.top, line.box.bottom - line.box.top)
                    and line.box.left - last.right <= .10):
                row.append(line)
                break
        else:
            rows.append([line])
    return [Line(" ".join(part.text for part in row),
                 Box(min(p.box.left for p in row), min(p.box.top for p in row),
                     max(p.box.right for p in row), max(p.box.bottom for p in row))) for row in rows]


def inspect_page(page: int, lines: list[Line], printed_bands: tuple[Box, ...] = ()) -> Finding:
    if not lines and not printed_bands:
        return Finding(NEEDS_REVIEW)
    rows = _numeric_rows(lines)
    bands = [(line, _micr_strength(line.text)) for line in rows]
    payees = [line for line in lines if PAYEE_LABEL.search(line.text)]
    signatures = [line for line in lines if re.search(r"\b(?:authorized signature|signature of issuer)\b", line.text, re.I)]
    labels = [(line, match[1]) for line in lines if (match := NUMBER_LABEL.search(line.text))]
    strong = bool(printed_bands) or any(score == 2 for _, score in bands)
    candidates = [line.box for line, score in bands if score]
    for printed in printed_bands:
        # Use the union if visual and optical evidence found the same band.
        overlaps = [b for b in candidates if b.top < printed.bottom and printed.top < b.bottom
                    and b.left < printed.right and printed.left < b.right]
        for box in overlaps:
            candidates.remove(box)
        group = [printed, *overlaps]
        candidates.append(Box(min(b.left for b in group), min(b.top for b in group),
                              max(b.right for b in group), max(b.bottom for b in group)))
    if not (strong or candidates or payees or (labels and signatures)):
        return Finding()
    # Optical readers sometimes join the routing and account fields into one
    # run of digits. Independent check-face labels corroborate that weaker band.
    corroborated = candidates and payees and (labels or signatures)
    finding = Finding("Check" if strong or corroborated else NEEDS_REVIEW)
    if len(printed_bands) > 1 or (len(payees) > 1 and len(candidates) > 1):
        finding.status = "Multiple check pages"
    for band in candidates:
        height = band.bottom - band.top
        finding.marks.append(Mark(page, "MICR", band.padded(.025, height * .45, height * .45)))
    for label in signatures:
        box = label.box
        height = box.bottom - box.top
        finding.marks.append(Mark(page, "Signature", box.padded(.05, max(.045, 2.3 * height), height * .5)))
    if len(labels) == 1:
        finding.number = labels[0][1]
    # Only offer an issuer from the check area. Ambiguous names remain blank.
    if payees:
        anchor = payees[0].box
        names = [line.text for line in lines if anchor.top - .30 < line.box.top < anchor.top
                 and abs(line.box.left - anchor.left) < .17 and ISSUER_SUFFIX.search(line.text)
                 and not re.search(r"\b(bank|payee|account|acct|routing)\b|\d{5,}", line.text, re.I)]
        if len(names) == 1:
            finding.issuer = names[0]
        if not finding.number:
            serials = [line.text for line in lines if re.fullmatch(r"\d{3,12}", line.text)
                       and anchor.top - .23 < line.box.top < anchor.top
                       and line.box.left > anchor.right]
            if len(serials) == 1:
                finding.number = serials[0]
    return finding


def combine_pages(pages: list[Finding]) -> Finding:
    candidates = [p for p in pages if p.status != "Unrelated"]
    if not candidates:
        return Finding()
    strong = [p for p in candidates if p.status == "Check"]
    primary = (strong or candidates)[0]
    result = Finding(primary.status, [m for p in candidates for m in p.marks],
                     primary.issuer, primary.number)
    if len(strong) > 1 or any(p.status == "Multiple check pages" for p in candidates):
        result.status = "Multiple check pages"
    return result
