FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py models.py backend_simulator.py aggregator.py openadr_vtn.py openadr_ven.py ./

# Default: run all backends. Override CMD for specific services.
CMD ["python", "backend_simulator.py"]
