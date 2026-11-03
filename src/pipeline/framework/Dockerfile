FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    git \
    curl \
    vim \
    nano \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

RUN pip install --no-cache-dir \
    gitpython \
    pydantic \
    click \
    rich \
    pathspec \
    pyyaml \
    openai \
    inspect_ai \
    pytest \
    pytest-asyncio \
    pytest-mock

# Per-codebase dependencies are installed by the generated Dockerfile
# (see packager.py _generate_dockerfile). This static Dockerfile is a
# template only; the packager copies it and adds codebase-specific deps.

CMD ["tail", "-f", "/dev/null"]
