# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm

# Install UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml .
COPY agentbench/ ./agentbench/
COPY cli/ ./cli/

# Install dependencies using UV
RUN uv pip install --system -e "."

# Create necessary directories
RUN mkdir -p /app/data/raw_io /app/fixtures/pr_review/cases

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run the application
CMD ["agentbench", "serve"]
