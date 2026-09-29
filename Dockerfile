# Stage 1: Builder
FROM python:3.13-slim AS builder

# Install build dependencies (C++, Go, Curl)
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    golang \
    && rm -rf /var/lib/apt/lists/*

# Install Rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Install maturin for PyO3
RUN pip install --no-cache-dir maturin

WORKDIR /build

# Copy source code
COPY . .

# Build Go Coordinator (fails gracefully if not fully integrated)
WORKDIR /build/coordinator
RUN go build -buildmode=c-shared -o libcoordinator.so src/main.go src/merge.go || echo "Go coordinator build skipped"

# Build Rust extension as a Python Wheel
WORKDIR /build/storage
RUN maturin build --release --out target/wheels

# ==========================================
# Stage 2: Runtime
# ==========================================
FROM python:3.13-slim

WORKDIR /app

# Install the built Python wheel from Stage 1
COPY --from=builder /build/storage/target/wheels/*.whl /tmp/
RUN pip install /tmp/*.whl && rm -rf /tmp/*.whl

# Copy the built Go coordinator
# Create directory first to avoid errors if the build skipped
RUN mkdir -p /app/coordinator
COPY --from=builder /build/coordinator/libcoordinator.so* /app/coordinator/

# Copy Python application files
COPY cleavedb.py /app/
COPY cleaveql/ /app/cleaveql/

# Create data directory for persistence mapping
RUN mkdir -p /app/cleavedb_data

# Set up volume
VOLUME ["/app/cleavedb_data"]

# Start the interactive REPL
CMD ["python", "cleavedb.py"]
