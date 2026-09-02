FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY config config
COPY scripts scripts
RUN useradd --create-home monitor && mkdir -p /app/data && chown -R monitor:monitor /app
USER monitor
CMD ["python", "-m", "app.main"]

