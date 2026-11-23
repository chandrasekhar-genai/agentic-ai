# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS build
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /install /usr/local
USER 10001
EXPOSE 8080
ENTRYPOINT ["uvicorn", "--factory", "aiops_agent.app:create_app", "--host", "0.0.0.0", "--port", "8080"]
