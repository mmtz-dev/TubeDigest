#!/bin/bash
set -e

# Create a user matching the host UID/GID so files on mounted volumes
# are owned by the host user instead of root.
PUID=${PUID:-1000}
PGID=${PGID:-1000}

if [ "$(id -u)" = "0" ]; then
    # Create group if it doesn't exist
    if ! getent group appuser > /dev/null 2>&1; then
        groupadd -g "$PGID" appuser
    fi

    # Create user if it doesn't exist
    if ! id appuser > /dev/null 2>&1; then
        useradd -u "$PUID" -g "$PGID" -m -s /bin/bash appuser
    fi

    # Ensure ownership of app directories
    chown -R appuser:appuser /app/Transcriptions /app/Summaries /home/.local /home/.cache

    # Run the command as appuser
    exec gosu appuser "$@"
fi

# If not root, just run the command directly
exec "$@"
