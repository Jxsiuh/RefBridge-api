"""
referral_extractor.py
----------------------
Step 1 of the RefBridge intake pipeline: turn a referral PDF (digital-text
OR scanned/faxed image) into plain text, then pull structured fields out
of that text using pattern matching.

Design choices (read this before you change anything):

1. NO external AI/API calls. Extraction is done with local regex patterns
   against text pulled straight off the PDF. This matters for two reasons:
     - PHI never leaves the machine running this script.
     - Behavior is 100% deterministic and debuggable — if a field doesn't
       extract, you can see exactly which pattern failed and fix it,
       instead of wondering why an LLM guessed wrong.
   A future version could hand messy/inconsistent referrals to an LLM for
   extraction instead of regex. If you do that with REAL patient data, the
   AI vendor call has to run through a BAA-covered endpoint — don't route
   real PHI through a plain API key.

2. Text-first, OCR-fallback. Digital PDFs (e-faxed, emailed, EHR exports)
   almost always have selectable text — pdfplumber pulls it instantly and
   perfectly. Scanned/faxed paper referrals have no text layer at all, so
   we fall back to rendering each page as an image and running Tesseract
   OCR on it. OCR is slower and less accurate, so we only use it when the
   text-layer approach comes up empty.
"""

import re
import pdfplumber
from pdf2image import convert_from_path
import pytesseract


# Below this many characters of extracted text, we assume the PDF has no
# real text layer (e.g. it's a scanned image wrapped in a PDF) and switch
# to OCR instead. A real referral page has way more text than this if the
# text layer exists at all.
MIN_TEXT_LENGTH_BEFORE_OCR_FALLBACK = 40


def extract_text(pdf_path: str) -> tuple[str, str]:
    """
    Pull all text out of a PDF, regardless of whether it's a digital
    (text-layer) PDF or a scanned image PDF.

    Returns (text, method) where method is "text_layer" or "ocr", so
    callers/logs can tell which path was used (OCR results are noisier
    and worth flagging for human review).
    """
    text_layer_chunks = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_layer_chunks.append(page_text)

    text_layer_result = "\n".join(text_layer_chunks).strip()

    if len(text_layer_result) >= MIN_TEXT_LENGTH_BEFORE_OCR_FALLBACK:
        return text_layer_result, "text_layer"

    # Fallback: no usable text layer, so render pages as images and OCR them.
    ocr_chunks = []
    pages_as_images = convert_from_path(pdf_path, dpi=300)
    for image in pages_as_images:
        ocr_chunks.append(pytesseract.image_to_string(image))

    return "\n".join(ocr_chunks).strip(), "ocr"


# Each field maps to a list of regex patterns, tried in order, to handle
# the fact that different clinics/EHRs label the same field differently
# (e.g. "DOB:" vs "Date of Birth:"). First match wins.
FIELD_PATTERNS = {
    "patient_name": [
        r"Patient\s*Name\s*[:\-]\s*(.+)",
        r"Patient\s*[:\-]\s*(.+)",
    ],
    "date_of_birth": [
        r"(?:Date\s*of\s*Birth|DOB)\s*[:\-]\s*([\d/\-]+)",
    ],
    "patient_phone": [
        r"Patient\s*Phone\s*[:\-]\s*([\d\-\(\)\s\.]{7,})",
        r"Phone\s*[:\-]\s*([\d\-\(\)\s\.]{7,})",
    ],
    "referring_provider": [
        r"Referring\s*(?:Physician|Provider|Doctor|MD)\s*[:\-]\s*(.+)",
        r"Referred\s*by\s*[:\-]\s*(.+)",
    ],
    "referral_date": [
        r"(?:Referral\s*Date|Date\s*of\s*Referral)\s*[:\-]\s*([\d/\-]+)",
    ],
    "diagnosis": [
        r"Diagnosis\s*[:\-]\s*(.+)",
    ],
    "icd10_code": [
        r"ICD[\-\s]?10\s*(?:Code)?\s*[:\-]\s*([A-Z]\d{2}\.?\d{0,4})",
        r"\b([A-Z]\d{2}\.\d{1,3})\b",  # bare ICD-10 code floating in text
    ],
    "insurance": [
        r"Insurance\s*(?:\/\s*Payer)?\s*[:\-]\s*(.+)",
        r"Payer\s*[:\-]\s*(.+)",
    ],
    "referred_to_clinic": [
        r"Refer(?:red)?\s*to\s*[:\-]\s*(.+)",
    ],
}


def parse_fields(text: str) -> dict:
    """
    Run every FIELD_PATTERNS entry against the extracted text and return
    a dict of {field_name: value_or_None}. Values are stripped of trailing
    junk (extra whitespace, trailing commas) but otherwise left as-is —
    no attempt to "clean up" formatting here, so it's obvious in the DB
    exactly what the source document actually said.
    """
    results = {}
    for field_name, patterns in FIELD_PATTERNS.items():
        value = None
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1).strip().rstrip(",;")
                break
        results[field_name] = value
    return results


def extraction_confidence(fields: dict) -> str:
    """
    Cheap signal for human review triage: what fraction of expected
    fields actually got a value. This is NOT a measure of whether the
    values are *correct* — just whether the patterns found anything.
    A human should always eyeball "low" and "medium" confidence rows
    before they're used to contact a patient.
    """
    found = sum(1 for v in fields.values() if v)
    total = len(fields)
    ratio = found / total if total else 0
    if ratio >= 0.8:
        return "high"
    elif ratio >= 0.5:
        return "medium"
    return "low"


def scan_referral(pdf_path: str) -> dict:
    """
    Full pipeline for one file: extract text (text-layer or OCR), parse
    fields out of it, and package everything a caller needs to store a
    profile and audit how it was derived.
    """
    text, extraction_method = extract_text(pdf_path)
    fields = parse_fields(text)
    confidence = extraction_confidence(fields)

    return {
        **fields,
        "source_file": pdf_path,
        "extraction_method": extraction_method,
        "confidence": confidence,
        "raw_text": text,
    }
