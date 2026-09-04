FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --system finai && useradd --system --gid finai finai
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

USER finai
EXPOSE 8000
CMD ["uvicorn", "finai_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
