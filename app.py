"""
app.py
------
Minimal web API around referral_extractor.scan_referral(), so Make.com
(which runs in the cloud and can't reach a script on Josiah's laptop)
has a URL to call instead.

This does NOT reimplement any extraction logic -- it's a thin wrapper.
Everything about how referrals get read stays exactly as tested in
referral_extractor.py.

Endpoints:
  GET  /              -> health check, confirms the service is up
  POST /scan-referral  -> body: {"pdf_base64": "<base64-encoded PDF>"}
                          returns the same JSON dict scan_referral() produces

Security: requires a shared API key on every /scan-referral request,
via the X-API-Key header. This endpoint is public on the internet, so
without this, anyone could send it referral PDFs. Set the real key as
an environment variable (API_KEY) on Render -- never hardcode it here.
"""

import base64
import os
import tempfile

from flask import Flask, request, jsonify

from referral_extractor import scan_referral

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY")


@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"})


@app.route("/scan-referral", methods=["POST"])
def scan_referral_endpoint():
    # Require the shared key on every real request. Fail closed: if
    # API_KEY was never configured on the server, refuse everything
    # rather than silently running with no security.
    provided_key = request.headers.get("X-API-Key")
    if not API_KEY or provided_key != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True)
    if not data or "pdf_base64" not in data:
        return jsonify({"error": "Missing 'pdf_base64' in request body"}), 400

    try:
        pdf_bytes = base64.b64decode(data["pdf_base64"])
    except Exception:
        return jsonify({"error": "pdf_base64 is not valid base64"}), 400

    # Write to a temp file since scan_referral() takes a file path --
    # no change needed to the already-tested extraction code.
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        tmp.write(pdf_bytes)
        tmp.flush()
        result = scan_referral(tmp.name)

    # source_file would just be a meaningless temp path here -- drop it
    # so the response doesn't imply a real file path exists server-side.
    result.pop("source_file", None)

    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
