# Weather Intelligence MCP Server

A weather intelligence MCP server built following the Navteca template tutorial.

## Features

Three tools for weather-based decisions:

1. **outdoor_activity_check** - Score conditions (0-100) for running, hiking, cycling
2. **surf_conditions** - Wave height, swell period, safety assessment for water sports  
3. **garden_watering_advisor** - Should you water today based on soil moisture and rain forecast

## API

Uses Open-Meteo (free, no API key required):
- Weather API
- Air Quality API
- Marine API
- Geocoding API

## Security Features

- Input validation with prompt injection detection
- Secure HTTP client with URL allowlisting
- TLS enforcement
- Response size limiting
- Retry with exponential backoff

## Secret Leak Prevention

This project includes baseline guardrails to reduce accidental secret exposure:

- `.gitignore` excludes `.env` files and private key material
- `.pre-commit-config.yaml` runs `gitleaks` before commits
- `make scan-secrets` performs a full workspace scan (`--no-git`)

### Setup

1. Install `gitleaks`
2. Install `pre-commit`
3. Run:

```bash
pre-commit install
pre-commit run --all-files
make scan-secrets
```

## Installation

```bash
pip install -e .
# or
uv sync
```

## Running

```bash
weather-intelligence-server
# or
python -m weather_intelligence.server
```
