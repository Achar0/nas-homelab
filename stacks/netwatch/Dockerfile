FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
# maxminddb reads the DB-IP geolocation database
RUN uv pip install --system --no-cache maxminddb==2.6.2
WORKDIR /app
COPY app.py ./
COPY static ./static
USER 1000:10
CMD ["python", "-u", "app.py"]
