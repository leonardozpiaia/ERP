FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_DEBUG=false

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Arquivos de estilo do painel, gerados na construção da imagem.
RUN DJANGO_SECRET_KEY=somente-para-o-build python manage.py collectstatic --noinput \
    && useradd --create-home --uid 1000 erp \
    && chmod +x deploy/iniciar.sh

USER erp
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/saude/', timeout=4)"

CMD ["deploy/iniciar.sh"]
