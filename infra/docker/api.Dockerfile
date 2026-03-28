FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl && \
    rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY apps/api/pyproject.toml apps/api/pyproject.toml
RUN pip install --no-cache-dir -e apps/api

# Copy application code
COPY apps/api/ apps/api/
COPY apps/worker/ apps/worker/
COPY packages/ packages/
COPY schemas/ schemas/
COPY parsers/ parsers/
COPY content/ content/
COPY jobs/ jobs/

# Set Python path to find packages
ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "apps.api.netgraphy_api.app:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
