# Use Python with Playwright pre-installed
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Playwright browsers are pre-installed in the base image

# Default command (can be overridden)
CMD ["python", "main.py"]
