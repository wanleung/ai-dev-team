FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN addgroup --system appuser && adduser --system --ingroup appuser appuser

COPY . .

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8001

CMD ["python", "-m", "uvicorn", "main:mcp_http_app", "--host", "0.0.0.0", "--port", "8001"]
