# Vayudoot, packaged for a free-tier container host.
#
# Hugging Face Spaces (Docker SDK) is the deployment target: no credit card, a
# public HTTPS URL, and it expects the service on port 7860. The image runs as
# uid 1000 because that is the user a Space runs as; anything the process writes
# has to be under that user's home.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH
WORKDIR /home/user/app

# Dependencies first: they change far less often than the source does.
COPY --chown=user pyproject.toml README.md ./
COPY --chown=user src ./src
RUN pip install --user --no-cache-dir .

# Cases, uploads, and the sandbox outbox. This disk is ephemeral on a free
# container — a restart loses filed cases, which is acceptable for a prototype
# and is why store.py is a single module to replace.
ENV VAYUDOOT_CASE_DIR=/home/user/data/cases \
    VAYUDOOT_UPLOAD_DIR=/home/user/data/uploads \
    VAYUDOOT_SANDBOX_OUTBOX=/home/user/data/outbox
RUN mkdir -p /home/user/data

# Safety: filing stays sandboxed in a deployed container unless someone changes
# this deliberately, and there is no transport wired in even if they do.
ENV VAYUDOOT_LIVE_FILING=false

EXPOSE 7860
CMD ["uvicorn", "vayudoot.api:app", "--host", "0.0.0.0", "--port", "7860"]
