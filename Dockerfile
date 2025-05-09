### Stage 1: Build environment with dependencies ###
FROM python:3.12-alpine AS builder

WORKDIR /app

# Install build tools for packages with native extensions
RUN apk add --no-cache build-base
# Copy and install dependencies into user-local path
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

### Stage 2: Minimal runtime image ###
FROM python:3.12-alpine

# Create a non-root user
RUN adduser -D appuser

WORKDIR /app

# Copy application and installed dependencies from builder stage
COPY --from=builder /app /app
COPY --from=builder /root/.local /home/appuser/.local

# Set correct PATH so that user-installed packages are found
ENV PATH=/home/appuser/.local/bin:$PATH

# Create a data directory and set permissions
RUN mkdir -p /app/data && chown -R appuser /app /home/appuser

# Switch to non-root user
USER appuser

CMD ["python", "run.py"]
