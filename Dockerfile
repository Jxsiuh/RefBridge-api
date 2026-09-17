FROM python:3.11-slim

# Tesseract (OCR) and poppler-utils (PDF-to-image rendering) -- the two
# system tools referral_extractor.py's OCR fallback path depends on.
# Render's default Python buildpack doesn't include these, which is
# exactly why this is a Docker service instead.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py referral_extractor.py ./

CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000", "--timeout", "60"]
