FROM postgres:18

RUN apt-get update && apt-get install -y \
    build-essential \
    pkg-config \
    git \
    curl \
    libssl-dev \
    postgresql-server-dev-18 \
    && rm -rf /var/lib/apt/lists/*

# Install Rust (non-interactive, default toolchain)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
ENV PATH="/root/.cargo/bin:${PATH}"

# Clone pg_jsonschema; pin the commit/tag you trust rather than HEAD for reproducibility.
RUN git clone --depth 1 https://github.com/supabase/pg_jsonschema.git /opt/pg_jsonschema

WORKDIR /opt/pg_jsonschema

# Derive the pgrx version the extension requires from its own Cargo.toml.
# This ensures cargo-pgrx and the extension always agree on the pgrx ABI.
RUN PGRX_VERSION=$(grep -m1 'pgrx\s*=' Cargo.toml \
        | grep -oP '(?<=version = ")[^"]+|(?<= = ")[^"]+' \
        | head -1) && \
    echo "Installing cargo-pgrx==${PGRX_VERSION}" && \
    cargo install cargo-pgrx --version "${PGRX_VERSION}" --locked

# Point pgrx at the already-installed Postgres 18 rather than letting it
# download its own Postgres source tree.
RUN cargo pgrx init --pg18 /usr/lib/postgresql/18/bin/pg_config

# Build and install the .so + .control files into the Postgres extension directory.
RUN cargo pgrx install --pg-config /usr/lib/postgresql/18/bin/pg_config --release

WORKDIR /
RUN rm -rf /opt/pg_jsonschema /root/.cargo /root/.rustup

# pgcrypto ships with postgres-contrib; no separate build needed.
