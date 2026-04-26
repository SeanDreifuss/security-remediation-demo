FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY orchestrator/ ./orchestrator/
COPY scripts/ ./scripts/

# Create log file
RUN touch webhook.log

# Expose the webhook port
EXPOSE 5000

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the webhook server
CMD ["python", "orchestrator/webhook_server.py"]