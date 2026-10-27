FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app MPLBACKEND=Agg PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.lock.txt .
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements.lock.txt
COPY . .
ENTRYPOINT ["python", "-m", "itb.cli"]
CMD ["analyze"]
