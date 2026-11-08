FROM python:3.12-slim
# Standard library only: no packages to install
WORKDIR /app
COPY server.py auth.py settings.py discovery.py guest.py feeds.py attention.py arrivals.py news_db.py weather.py iptv.py feeds.json ./
COPY static ./static
USER 1000:10
CMD ["python", "-u", "server.py"]
