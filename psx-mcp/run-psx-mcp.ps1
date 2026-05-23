# Launch the PSX MCP server on http://127.0.0.1:8765/sse
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
uv run python server.py
