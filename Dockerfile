# Project VeriMed – Docker-Image mit Tesseract-OCR (Kamera-Rechnungserkennung)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Systemabhaengigkeiten: Tesseract OCR (+ deutsches Sprachpaket) fuer die
# Rechnungs-Texterkennung sowie Build-/Bildverarbeitungs-Bibliotheken fuer
# Pillow/OpenCV-nahe Abhaengigkeiten.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-deu \
    libtesseract-dev \
    gcc \
    ffmpeg \
    libsm6 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
