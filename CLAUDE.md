# RefBridge — Project Context for Claude Code

RefBridge is an AI-powered referral management and patient-activation platform for independent PT clinics in the DFW area (Josiah's startup, RefBridge LLC — not yet legally formed). It works **alongside** a clinic's existing EMR, not as a replacement: it's a pre-visit layer that scans incoming referrals, creates a lightweight patient-activation record, and automatically follows up with the patient by text to get them scheduled. It hands off to the clinic's real EMR once the patient books.

**Architecture philosophy:** hybrid build. No-code (Airtable + Make.com) handles storage, workflow, and Twilio triggering. Custom code stays narrow — limited to the referral-scanning/OCR extraction service. Don't expand the custom-code footprint without a specific reason; the no-code layer is intentional, not a placeholder to replace.

## What's built and proven (tested end-to-end, working)

**1. Extraction service** — `referral_extractor.py`
- Opens a referral PDF, tries `pdfplumber` text-layer extraction first, falls back to Tesseract OCR (via `pdf2image`) if the text layer is empty/too short (i.e. a scanned/faxed image with no real text)
- Regex-based field extraction (`FIELD_PATTERNS`) pulls: patient_name, date_of_birth, patient_phone, referring_provider, referral_date, diagnosis, icd10_code, insurance, referred_to_clinic
- Deliberately **not** AI/LLM-based — keeps PHI local, deterministic, debuggable. (A Make.com AI module or Airtable Field Agents/Omni could potentially replace this — flagged as worth exploring, not yet tested. Don't switch without comparing outputs side-by-side against the current regex extraction on real referrals.)
- `extraction_confidence()` gives high/medium/low based on how many fields were found — drives the human-review gate downstream

**2. Hosted API** — `app.py` + `Dockerfile` + `requirements.txt`
- Flask wrapper: `POST /scan-referral` accepts `{"pdf_base64": "..."}`, returns the same JSON dict `scan_referral()` produces
- Requires `X-API-Key` header — checked against the `API_KEY` environment variable on the server (get the actual key value from Render's dashboard/env vars, don't hardcode it anywhere)
- Deployed on **Render** as a Docker service (not the plain Python buildpack — Tesseract/poppler need apt-get, hence Docker)
- Service name: `refbridge-referral-scanner`, live at `https://refbridge-referral-scanner.onrender.com`
- Source repo: `https://github.com/Jxsiuh/RefBridge-api` (public)

**3. Airtable** — base `RefBridge` (ID `appMdx1qhC02R9u3U`), table `Referrals` (ID `tblQFCs0tjF5cPLJ7`)
- Fields: Patient Name, Date of Birth, Patient Phone, Referring Provider, Referral Date, Diagnosis, ICD-10 Code, Insurance, Referred To Clinic, Status (single-select: New/Needs Review/Texted/Scheduled/No Response), Confidence (single-select: high/medium/low), Extraction Method (text_layer/ocr), Source File (attachment), Raw Text, Notes
- Interface `RefBridge Staff View` (ID `pbdBGgg4k6L0LL2nL`), published and live:
  - `Referral Queue` page — grid with "Needs Review" tab (Confidence ≠ high) and "New Referrals" tab (Status = New)
  - `Referral Detail` page — editable record view for correcting misreads, shown side-by-side with the original extracted text

**4. Make.com scenario** — `RefBridge Referral Intake` (scenario ID `6316357`), webhook ID `2827810`
- Flow: Custom Webhook trigger → HTTP POST to the Render API → Airtable Create Record → Twilio Send SMS
- Twilio "to" field normalizes the raw extracted phone string to E.164 (strips `()`, spaces, dashes, dots, prepends `+1`) — the extractor returns phone numbers exactly as written on the source document, so this normalization has to happen somewhere before Twilio
- **Gotcha:** Make auto-deactivates this scenario after errors. Check `isActive` before assuming a test will actually run, and reactivate if needed.
- **Gotcha:** webhook GET requests to the same URL get cached by mobile browsers — append a throwaway `&t=<timestamp>` query param when retesting to force a fresh hit.
- **Gotcha:** `scenarios_run` (direct API invocation) does NOT reliably simulate a real webhook hit for this scenario — it silently no-ops. Real tests need an actual HTTP request to the live webhook URL.

**5. Twilio**
- Trial upgraded with $20 balance (paid, no LLC needed for that step)
- Sendable number: `+18557541630` (toll-free)
- Custom message bodies work now (trial's "predefined templates only" restriction is gone post-upgrade)
- **Blocked:** toll-free number requires carrier verification before it can actually deliver (not just queue) messages. That verification form requires an EIN and a live business website with Privacy Policy + Terms & Conditions pages — neither exists yet (see Outstanding below).

## Outstanding / blocked — not a coding problem, needs business formation first

1. **Form RefBridge LLC** → gives an EIN
2. **Buy a domain** → gives somewhere to host a business website
3. **Minimal website with Privacy Policy + Terms & Conditions pages**
4. **Submit Twilio toll-free verification** with the above → few business days for approval → real SMS delivery finally works (scenario itself needs no changes)
5. **Real fax intake** — lives in its own repo now, **not** in RefBridge-api: [`refbridge-fax-intake`](https://github.com/Jxsiuh/refbridge-fax-intake) (private). It watches a mailbox via IMAP and forwards each PDF attachment to the same Make.com webhook this repo's scenario already uses (extraction/Airtable/Twilio all stay here, unchanged). Only the attachment-parsing and webhook-forwarding logic is tested (synthetic email, mocked webhook call) — the live IMAP connection has never touched a real mailbox. Still needs: a HIPAA-compliant cloud fax provider with a signed BAA that delivers incoming faxes as PDF email attachments, and a BAA-covered email inbox (Google Workspace/Microsoft 365 paid tier) for that provider to deliver to.

## Working style Josiah prefers

- Detailed, structured responses (headers/bullets), not dense prose
- Explain the *why* behind technical decisions, not just the *what*
- Flag risks/flawed assumptions directly rather than silently proceeding
- Prioritize accuracy — flag uncertainty explicitly rather than guessing
- Test claims for real (run the code, check the actual API response, check the actual database row) rather than asserting something "should" work
