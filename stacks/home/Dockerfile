FROM python:3.12-slim
# Standard library plus cryptography (passkey signatures)
WORKDIR /app
RUN pip install --no-cache-dir cryptography==50.0.2
COPY server.py auth.py passkeys.py settings.py discovery.py guest.py feeds.py attention.py arrivals.py news_db.py weather.py iptv.py feeds.json ./
COPY static ./static
USER 1000:10
CMD ["python", "-u", "server.py"]
