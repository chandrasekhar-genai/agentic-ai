# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS build
WORKDIR /build
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DOCS_DIR=/srv/data/docs
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /install /usr/local
COPY data /srv/data
USER 10001
EXPOSE 8080
CMD ["uvicorn", "--factory", "rag.api:create_app", "--host", "0.0.0.0", "--port", "8080"]
