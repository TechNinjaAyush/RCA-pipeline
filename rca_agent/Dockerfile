# Stage 1: Builder
FROM python:3.11-slim AS builder

# Set the working directory
WORKDIR /app


# Copy the requirements file
COPY requirements.txt .

# Create a virtual environment and install dependencies
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install python packages
RUN pip3 install --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM gcr.io/distroless/python3-debian12:nonroot

# Run as nonroot user (UID 65532 in distroless)
USER 65532:65532

# Set the working directory
WORKDIR /app

# Copy the virtual environment from the builder stage
COPY --from=builder --chown=65532:65532 /opt/venv /opt/venv

# Set PYTHONPATH so the distroless python can find the installed packages
ENV PYTHONPATH="/opt/venv/lib/python3.11/site-packages"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copy the application code
COPY --chown=65532:65532 . .

# Run the application (Distroless python3 image has ENTRYPOINT ["/usr/bin/python3"])
CMD ["main.py"]