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

# Configure git identity for commits made during image build and eval.
RUN git config --global user.email "dev@example.com" && \
    git config --global user.name "Developer"

COPY baseline /workspace/petri

# Generate _version.py stub so the local source tree is importable.
RUN pkg_dir=$(echo "petri" | tr '-' '_') && \
    if [ -d "/workspace/petri/src/${pkg_dir}" ]; then \
        echo '__version__ = "0.0.0+sandbox"' > "/workspace/petri/src/${pkg_dir}/_version.py"; \
    elif [ -d "/workspace/petri/${pkg_dir}" ]; then \
        echo '__version__ = "0.0.0+sandbox"' > "/workspace/petri/${pkg_dir}/_version.py"; \
    fi

# Install Python target packages after the baseline has been copied into place.
RUN cd /workspace/petri && \
    if [ -f pyproject.toml ] || [ -f setup.py ] || [ -f setup.cfg ]; then \
        python -m pip install --no-cache-dir -e .; \
    fi

# Pre-commit the baseline so Inspect sandbox startup and diff extraction have a
# stable repository state.
RUN cd /workspace/petri && \
    git init && \
    git add -A && \
    git commit -m "Initial baseline state" --allow-empty && \
    git config core.filemode false

LABEL pipeline.run_id="petri-demo" pipeline.codebase="petri"

CMD ["tail", "-f", "/dev/null"]
