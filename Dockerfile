FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app files
COPY dashboard.py .
COPY reports/ reports/
COPY pipeline/ pipeline/
COPY data/ data/

# Cloud Run uses $PORT env var (defaults to 8080)
EXPOSE 8080

# Run streamlit on Cloud Run
CMD ["streamlit", "run", "dashboard.py", \
     "--server.port=${PORT:-8080}", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
