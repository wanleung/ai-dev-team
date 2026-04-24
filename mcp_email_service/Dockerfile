FROM python:3.12-slim

WORKDIR /app

COPY mcp_email_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_email_service/ .

ENV PORT=8000
ENV TESTING=true
ENV DATABASE_URL=sqlite+aiosqlite:///./test.db
ENV DEBUG=true

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
