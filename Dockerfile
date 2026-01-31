FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-rus && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# сначала зависимости (чтоб кэшировалось)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# потом код
COPY . /app

CMD ["python", "main.py"]
