# Dockerfile for DTC FAQ Reader - Hybrid Search
# Pre-caches both dense and sparse ML models for faster runtime

FROM python:3.12-slim as base

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Install ML dependencies for model pre-caching
RUN uv pip install sentence-transformers==3.0.1 fastembed==0.7.3 --system

# Pre-download dense embedding model
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('multi-qa-mpnet-base-dot-v1')"

# Pre-download sparse embedding model (SPLADE)
RUN python -c "from fastembed import SparseTextEmbedding; SparseTextEmbedding('prithvida/Splade_PP_en_v1')"

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser
RUN chown -R appuser:appuser /app
USER appuser

# Set entrypoint
ENTRYPOINT ["python", "data-ingestion/scripts/gdoc_faq_reader.py"]