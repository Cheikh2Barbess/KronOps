FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

COPY . .

# Ne tourne pas en root dans le conteneur.
RUN useradd --create-home kronops && chown -R kronops /app
USER kronops

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
