FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y tesseract-ocr tesseract-ocr-rus && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "main.py"]
