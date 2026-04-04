# syntax=docker/dockerfile:1

# Stage 1: Builder
FROM python:3.12-slim-bookworm AS builder

WORKDIR /app

# Install UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy source code and project metadata for building
COPY pyproject.toml .
COPY agentbench/ ./agentbench/
COPY cli/ ./cli/
COPY README.md .

# Install only production dependencies using cache mount
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-cache "."

# Stage 2: Runtime
FROM python:3.12-slim-bookworm AS runtime

# OCI Labels
LABEL org.opencontainers.image.title="AgentBench"
LABEL org.opencontainers.image.version="0.1.0"
LABEL org.opencontainers.image.description="AI evaluation framework for PR review behavior"
LABEL org.opencontainers.image.source="https://github.com/aluiziolira/agentbench"

WORKDIR /app

# Install tini for proper signal handling (PID 1)
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy app code with proper ownership
COPY --chown=appuser:appuser agentbench/ ./agentbench/
COPY --chown=appuser:appuser cli/ ./cli/

# Create necessary directories with proper ownership
RUN mkdir -p /app/data/raw_io /app/fixtures/pr_review/cases && \
    chown -R appuser:appuser /app/data /app/fixtures

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check with 10s start-period for proper container initialization
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)" || exit 1

# Use tini as entrypoint for proper signal handling, then run the application
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["agentbench", "serve"]
