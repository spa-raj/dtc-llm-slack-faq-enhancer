# Dockerfile for DTC FAQ Reader - Hybrid Execution
# Pre-caches ML models for faster runtime, expects dependencies installed by workflow

FROM python:3.12-slim as base

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Install sentence-transformers for model pre-caching
RUN uv pip install sentence-transformers==3.0.1 --system

# Pre-download the embedding model to speed up runtime
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('multi-qa-mpnet-base-dot-v1')"

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser
RUN chown -R appuser:appuser /app
USER appuser

# Set entrypoint
ENTRYPOINT ["python", "data-ingestion/scripts/gdoc_faq_reader.py"]