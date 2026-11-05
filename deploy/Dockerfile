# JARVIS-OS Production Dockerfile
# Multi-stage build for minimal runtime image

# =============================================================================
# Build stage - install dependencies
# =============================================================================
FROM python:3.11-slim AS builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy and install Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && \
    pip install -r /tmp/requirements.txt

# =============================================================================
# Runtime stage - minimal image
# =============================================================================
FROM python:3.11-slim AS runtime

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    JARVIS_CONFIG_PATH="/etc/jarvis/config.yaml" \
    JARVIS_DATA_DIR="/var/lib/jarvis" \
    JARVIS_LOG_DIR="/var/log/jarvis"

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user
RUN groupadd -r -g 1000 jarvis && \
    useradd -r -u 1000 -g jarvis -d /home/jarvis -s /bin/bash jarvis && \
    mkdir -p /home/jarvis && chown jarvis:jarvis /home/jarvis

# Create directories
RUN mkdir -p \
    /etc/jarvis \
    /var/lib/jarvis \
    /var/log/jarvis \
    /var/run/jarvis && \
    chown -R jarvis:jarvis /etc/jarvis /var/lib/jarvis /var/log/jarvis /var/run/jarvis

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application code
COPY --chown=jarvis:jarvis /tmp/jarvis-os /app/jarvis-os
WORKDIR /app/jarvis-os

# Install JARVIS-OS in development mode
RUN pip install -e .

# Switch to non-root user
USER jarvis

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Expose ports
EXPOSE 8080 9090

# Default command
CMD ["python", "-m", "jarvis.cli", "serve", "--host", "0.0.0.0", "--port", "8080"]