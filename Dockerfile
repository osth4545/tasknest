FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home appuser
COPY --chown=appuser:appuser app.py ./
COPY --chown=appuser:appuser templates ./templates
COPY --chown=appuser:appuser static ./static
USER appuser
EXPOSE 8000
CMD ["sh", "-c", "flask --app app:create_app init-db && waitress-serve --host=0.0.0.0 --port=8000 --call app:create_app"]
