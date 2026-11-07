FROM python:3.12-slim
# Standard library only: no packages to install
WORKDIR /app
COPY sources.py collector.py ./
USER 1000:10
CMD ["python", "-u", "collector.py"]
