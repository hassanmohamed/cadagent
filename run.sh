#!/bin/sh
# Start the demo and open it in the browser.
cd "$(dirname "$0")" || exit 1
(sleep 4 && open http://localhost:8000) &
exec uv run uvicorn cadagent.app:app --port 8000
