# ═══════════════════════════════════════════════════════════════════════════════
# ADIE — Backend Container
# Python 3.10 + conda (required for pythonocc-core) + FastAPI + Gemini SDK
# ═══════════════════════════════════════════════════════════════════════════════

FROM continuumio/miniconda3:latest

WORKDIR /app

# ── System libs required by pythonocc-core (OpenGL / X rendering) ─────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglu1-mesa \
    libxext6 \
    libxrender1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Conda environment (installs pythonocc-core from conda-forge) ──────────────
COPY environment.yml ./
RUN conda env create -f environment.yml && conda clean -afy

# ── Pip dependencies (FastAPI stack + AI SDK) ─────────────────────────────────
COPY requirements.txt ./
RUN /opt/conda/envs/adie/bin/pip install --no-cache-dir -r requirements.txt

# Always use the adie conda environment
ENV PATH="/opt/conda/envs/adie/bin:$PATH"

# ── Copy project source ───────────────────────────────────────────────────────
COPY . /app/

# ── Ensure runtime data directories exist ─────────────────────────────────────
RUN mkdir -p data/step_exports validation_scripts standards

# ── FastAPI backend on 0.0.0.0:8000 ──────────────────────────────────────────
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
