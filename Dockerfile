# ════════════════════════════════════════════════════════════════════════════
# ADIE Docker Environment
# Preserves the pythonocc-core, PyMuPDF, and generative AI toolchain.
# ════════════════════════════════════════════════════════════════════════════

FROM continuumio/miniconda3:latest

# Set up working directory
WORKDIR /app

# Install system dependencies (GL lib required for pythonocc-core)
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglu1-mesa \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Copy environment files
COPY environment.yml requirements.txt ./

# 1. Create the conda environment with pythonocc-core
RUN conda env create -f environment.yml

# 2. Install pip dependencies directly into the conda environment path
# We run pip inside the virtual environment explicitly to avoid pathing issues
RUN /opt/conda/envs/adie/bin/pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project
COPY . /app/

# Set the default shell to use the adie conda environment
SHELL ["conda", "run", "-n", "adie", "/bin/bash", "-c"]

# Make sure all bash calls inside docker use conda adie as default environment
RUN echo "conda activate adie" >> ~/.bashrc
ENV PATH="/opt/conda/envs/adie/bin:$PATH"

# Setup entrypoint so that when container runs, it lands in the adie env
CMD ["/bin/bash"]
