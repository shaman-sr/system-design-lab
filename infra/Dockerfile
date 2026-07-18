FROM python:3.13-trixie

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*

ADD https://astral.sh/uv/install.sh /uv-installer.sh

RUN sh /uv-installer.sh && rm /uv-installer.sh

# Ensure the installed binary is on the `PATH
ENV PATH="/root/.local/bin/:$PATH"

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-install-project

COPY . .

RUN uv sync --frozen

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
