FROM python:3.12-slim
# Standard library only: no packages to install
WORKDIR /app
COPY server.py auth.py ./
COPY static ./static
USER 1000:10
CMD ["python", "-u", "server.py"]
