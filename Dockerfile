FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl gosu && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    npm install -g @anthropic-ai/claude-code && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/Transcriptions /app/Summaries /home/.local/share/tubedigest

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV RUNNING_IN_DOCKER=true
ENV PORT=5555

EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/api/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "app.py"]
