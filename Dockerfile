# Container image for running the tweetkit-x MCP server (used by Smithery & general hosting).
FROM python:3.12-slim

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir ".[mcp]"

# The server speaks MCP over stdio.
ENTRYPOINT ["tweetkit-mcp"]
