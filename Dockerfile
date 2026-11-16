# Imagem de deploy do app Flask (o desenvolvimento continua no .venv).
# Uso no servidor: veja docker-compose.yml.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
# gunicorn só no deploy: no Windows do desenvolvimento ele não roda
RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.0.0

COPY app.py .
COPY scripts ./scripts
COPY static ./static
COPY templates ./templates

# Sem root dentro do contêiner
RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8000

# gthread: o app usa um pool de conexões com threads (ThreadedConnectionPool)
# e caches em memória por processo; poucos processos com várias threads
# aproveitam melhor os dois.
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000", \
     "--worker-class", "gthread", "--workers", "2", "--threads", "8", \
     "--timeout", "120", "--access-logfile", "-"]
