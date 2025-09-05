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

# Set up Python environment and optimized cache locations
WORKDIR /models

# Set cache directories to temporary locations for smaller image size
ENV TRANSFORMERS_CACHE=/tmp/transformers
ENV SENTENCE_TRANSFORMERS_HOME=/tmp/sentence_transformers
ENV HF_HOME=/tmp/huggingface

# Create cache directories
RUN mkdir -p /tmp/transformers /tmp/sentence_transformers /tmp/huggingface

# Install dependencies using the gdoc-faq dependency group
COPY pyproject.toml uv.lock ./
ENV UV_PROJECT_ENVIRONMENT=/usr/local
RUN uv sync --frozen --no-install-project --group gdoc-faq --no-cache && \
    uv pip install --system --no-cache-dir \
    torch --extra-index-url https://download.pytorch.org/whl/cpu && \
    uv cache clean

# Pre-download models with error handling, timeout, and optimized caching
RUN echo "Downloading dense embedding model..." && \
    timeout 300 python -c "from sentence_transformers import SentenceTransformer; print('Loading model...', flush=True); SentenceTransformer('multi-qa-mpnet-base-dot-v1'); print('Dense model cached!', flush=True)" && \
    echo "Downloading sparse embedding model..." && \
    timeout 300 python -c "from fastembed import SparseTextEmbedding; print('Loading SPLADE...', flush=True); SparseTextEmbedding('prithivida/Splade_PP_en_v1'); print('Sparse model cached!', flush=True)" && \
    echo "Models downloaded successfully" && \
    du -sh /tmp/transformers /tmp/sentence_transformers /tmp/huggingface 2>/dev/null || echo "Cache directories size check completed"

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

# Copy Python packages from builder stage (optimized cache handling)
COPY --from=model-downloader /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=model-downloader /tmp/transformers /tmp/transformers
COPY --from=model-downloader /tmp/sentence_transformers /tmp/sentence_transformers
COPY --from=model-downloader /tmp/huggingface /tmp/huggingface

# Set runtime cache environment variables
ENV TRANSFORMERS_CACHE=/tmp/transformers
ENV SENTENCE_TRANSFORMERS_HOME=/tmp/sentence_transformers
ENV HF_HOME=/tmp/huggingface

# Create non-root user and set permissions
RUN groupadd -r appuser && useradd -r -g appuser -m appuser \
    && chown -R appuser:appuser /app \
    && chown -R appuser:appuser /tmp/transformers \
    && chown -R appuser:appuser /tmp/sentence_transformers \
    && chown -R appuser:appuser /tmp/huggingface

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sentence_transformers, fastembed; print('OK')" || exit 1

# Set entrypoint
ENTRYPOINT ["python", "data-ingestion/scripts/gdoc_faq_reader.py"]