FROM python:3.9-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port for the application
EXPOSE 10000

# Set environment variables
ENV PORT=10000

# Run the application
CMD gunicorn app:app --bind 0.0.0.0:$PORT