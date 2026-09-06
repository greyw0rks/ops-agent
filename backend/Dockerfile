FROM python:3.12-slim

WORKDIR /app

# Install uv for faster dependency installation
RUN pip install uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen

# Copy application code
COPY app ./app
COPY scripts ./scripts

# Expose port
EXPOSE 8010

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8010/health')"

# Run the API server
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
