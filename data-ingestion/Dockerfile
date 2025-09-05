# Dockerfile for DTC FAQ Reader - Hybrid Search
# Optimized multi-stage build with model pre-caching

# Stage 1: Model download stage (runs as root for permissions)
FROM python:3.12-slim AS model-downloader

# Install system dependencies in one layer
RUN apt-get update && apt-get install -y \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set up Python environment
WORKDIR /models

# Install dependencies using the gdoc-faq dependency group
COPY pyproject.toml uv.lock ./
ENV UV_PROJECT_ENVIRONMENT=/usr/local
RUN uv sync --frozen --no-install-project --group gdoc-faq && \
    uv pip install --system --no-cache-dir \
    torch --extra-index-url https://download.pytorch.org/whl/cpu

# Pre-download models with error handling and timeout
RUN echo "Downloading dense embedding model..." && \
    timeout 300 python -c "from sentence_transformers import SentenceTransformer; print('Loading model...', flush=True); SentenceTransformer('multi-qa-mpnet-base-dot-v1'); print('Dense model cached!', flush=True)"

RUN echo "Downloading sparse embedding model..." && \
    timeout 300 python -c "from fastembed import SparseTextEmbedding; print('Loading SPLADE...', flush=True); SparseTextEmbedding('prithivida/Splade_PP_en_v1'); print('Sparse model cached!', flush=True)"

# Stage 2: Runtime stage
FROM python:3.12-slim AS runtime

# Install only runtime dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy Python packages and models from builder stage
COPY --from=model-downloader /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=model-downloader /root/.cache /root/.cache

# Create non-root user and set permissions
RUN groupadd -r appuser && useradd -r -g appuser -m appuser \
    && chown -R appuser:appuser /app \
    && chown -R appuser:appuser /root/.cache

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sentence_transformers, fastembed; print('OK')" || exit 1

# Set entrypoint
ENTRYPOINT ["python", "data-ingestion/scripts/gdoc_faq_reader.py"]