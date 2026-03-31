"""
Weather Intelligence MCP Server.

Provides three weather-related tools using Open-Meteo API (no API key required):
1. outdoor_activity_check - Score conditions for running, hiking, cycling
2. surf_conditions - Check ocean conditions for surfing, kayaking, swimming
3. garden_watering_advisor - Should you water your garden today?

Built following MCP best practices with security hardening:
- Input validation with prompt injection detection
- Secure HTTP client with URL allowlisting
- Rate limiting and audit logging
"""

import asyncio
import logging
import os
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from weather_intelligence.http_client import SecureHTTPClient
from weather_intelligence.validation import (
    Validator,
    check_prompt_injection,
    validate,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("MCP_PORT", "8000"))

mcp = FastMCP(
    name="weather-intelligence",
    instructions="Weather intelligence tools for outdoor activities, surfing, and gardening",
    host=MCP_HOST,
    port=MCP_PORT,
)

# ---------------------------------------------------------------------------
# Open-Meteo base URLs (no API key needed)
# ---------------------------------------------------------------------------
WEATHER_API = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_API = "https://air-quality-api.open-meteo.com/v1/air-quality"
MARINE_API = "https://marine-api.open-meteo.com/v1/marine"
GEOCODING_API = "https://geocoding-api.open-meteo.com/v1/search"

_http = SecureHTTPClient(
    allowed_base_urls=[
        "https://api.open-meteo.com",
        "https://air-quality-api.open-meteo.com",
        "https://marine-api.open-meteo.com",
        "https://geocoding-api.open-meteo.com",
    ],
    max_response_bytes=2 * 1024 * 1024,
)


async def _geocode(city: str) -> dict:
    """Resolve a city name to coordinates via Open-Meteo geocoding."""
    data = await _http.get(GEOCODING_API, params={"name": city, "count": 1})
    results = data.get("results")
    if not results:
        raise ValueError(f"City not found: {city}")
    hit = results[0]
    return {
        "name": hit["name"],
        "country": hit.get("country", ""),
        "latitude": hit["latitude"],
        "longitude": hit["longitude"],
    }


# ---------------------------------------------------------------------------
# Tool 1: Outdoor activity advisor
# ---------------------------------------------------------------------------

def _rate_conditions(
    temp_c: float,
    wind_kmh: float,
    rain_pct: float,
    uv: float,
    aqi: int,
) -> dict:
    """Score outdoor conditions and return a recommendation."""
    issues = []
    score = 100

    if temp_c < 5:
        score -= 30
        issues.append(f"Very cold ({temp_c:.0f}°C) — dress in layers")
    elif temp_c < 15:
        score -= 10
        issues.append(f"Cool ({temp_c:.0f}°C) — bring a jacket")
    elif temp_c > 35:
        score -= 40
        issues.append(f"Dangerously hot ({temp_c:.0f}°C) — avoid prolonged exposure")
    elif temp_c > 30:
        score -= 20
        issues.append(f"Hot ({temp_c:.0f}°C) — stay hydrated")

    if wind_kmh > 50:
        score -= 30
        issues.append(f"Dangerous winds ({wind_kmh:.0f} km/h)")
    elif wind_kmh > 30:
        score -= 15
        issues.append(f"Strong winds ({wind_kmh:.0f} km/h)")

    if rain_pct > 70:
        score -= 25
        issues.append(f"High rain probability ({rain_pct:.0f}%)")
    elif rain_pct > 40:
        score -= 10
        issues.append(f"Moderate rain chance ({rain_pct:.0f}%)")

    if uv >= 8:
        score -= 20
        issues.append(f"Very high UV index ({uv:.1f}) — sunscreen essential")
    elif uv >= 6:
        score -= 10
        issues.append(f"High UV ({uv:.1f}) — wear sunscreen")

    if aqi > 150:
        score -= 35
        issues.append(f"Unhealthy air (AQI {aqi}) — avoid outdoor exercise")
    elif aqi > 100:
        score -= 15
        issues.append(f"Moderate air quality (AQI {aqi}) — sensitive groups beware")

    score = max(0, score)

    if score >= 80:
        verdict = "Great conditions — get outside!"
    elif score >= 60:
        verdict = "Decent conditions with some caveats"
    elif score >= 40:
        verdict = "Marginal — consider indoor alternatives"
    else:
        verdict = "Poor conditions — best to stay indoors"

    return {"score": score, "verdict": verdict, "issues": issues}


@mcp.tool()
@validate(city=lambda v: check_prompt_injection(v) or Validator.length(v, max_len=200))
async def outdoor_activity_check(
    city: Annotated[str, Field(description="City name (e.g. 'Tokyo', 'São Paulo', 'Portland')")],
) -> dict:
    """Evaluate whether current conditions are suitable for outdoor activities.

    Analyzes temperature, wind, rain probability, UV index, and air quality
    to produce a 0-100 score with specific recommendations. Useful for
    deciding whether to go running, hiking, cycling, or have an outdoor event.
    """
    geo = await _geocode(city)
    lat, lon = geo["latitude"], geo["longitude"]

    weather, aqi_data = await asyncio.gather(
        _http.get(WEATHER_API, params={
            "latitude": lat, "longitude": lon,
            "current": "temperature_2m,apparent_temperature,wind_speed_10m,"
                       "wind_gusts_10m,precipitation_probability,uv_index",
            "timezone": "auto",
        }),
        _http.get(AIR_QUALITY_API, params={
            "latitude": lat, "longitude": lon,
            "current": "us_aqi,pm2_5,pm10",
        }),
    )

    current_weather = weather["current"]
    current_aqi = aqi_data["current"]

    rating = _rate_conditions(
        temp_c=current_weather["temperature_2m"],
        wind_kmh=current_weather["wind_speed_10m"],
        rain_pct=current_weather.get("precipitation_probability", 0),
        uv=current_weather["uv_index"],
        aqi=current_aqi.get("us_aqi", 0),
    )

    return {
        "location": f"{geo['name']}, {geo['country']}",
        "conditions": {
            "temperature_c": current_weather["temperature_2m"],
            "feels_like_c": current_weather["apparent_temperature"],
            "wind_kmh": current_weather["wind_speed_10m"],
            "wind_gusts_kmh": current_weather["wind_gusts_10m"],
            "rain_probability_pct": current_weather.get("precipitation_probability", 0),
            "uv_index": current_weather["uv_index"],
            "air_quality_aqi": current_aqi.get("us_aqi", 0),
            "pm2_5": current_aqi.get("pm2_5", 0),
        },
        **rating,
    }


# ---------------------------------------------------------------------------
# Tool 2: Surf and ocean conditions
# ---------------------------------------------------------------------------

@mcp.tool()
@validate(city=lambda v: check_prompt_injection(v) or Validator.length(v, max_len=200))
async def surf_conditions(
    city: Annotated[str, Field(
        description="Coastal city name (e.g. 'Honolulu', 'Biarritz', 'Cape Town')"
    )],
) -> dict:
    """Check ocean conditions for surfing, kayaking, or swimming.

    Returns wave height, swell period, wind, and a safety assessment.
    Best used for coastal cities — inland cities will return zeroed-out
    marine data since Open-Meteo has no ocean readings for those locations.
    """
    geo = await _geocode(city)
    lat, lon = geo["latitude"], geo["longitude"]

    marine, weather = await asyncio.gather(
        _http.get(MARINE_API, params={
            "latitude": lat, "longitude": lon,
            "current": "wave_height,wave_direction,wave_period,"
                       "swell_wave_height,swell_wave_period",
            "daily": "wave_height_max",
            "timezone": "auto",
            "forecast_days": 3,
        }),
        _http.get(WEATHER_API, params={
            "latitude": lat, "longitude": lon,
            "current": "wind_speed_10m,wind_gusts_10m,temperature_2m",
            "timezone": "auto",
        }),
    )

    current_weather = weather["current"]
    current_marine = marine.get("current", {})
    wave_h = current_marine.get("wave_height", 0)
    swell_h = current_marine.get("swell_wave_height", 0)
    swell_period = current_marine.get("swell_wave_period", 0)
    wind = current_weather["wind_speed_10m"]
    gusts = current_weather["wind_gusts_10m"]

    warnings = []
    if wave_h > 3:
        warnings.append(f"Large waves ({wave_h:.1f}m) — experienced surfers only")
    if wave_h > 5:
        warnings.append(f"Dangerous wave height ({wave_h:.1f}m) — stay out of the water")
    if gusts > 50:
        warnings.append(f"Dangerous wind gusts ({gusts:.0f} km/h)")
    if wind > 40:
        warnings.append(f"Strong winds ({wind:.0f} km/h) — choppy conditions")

    if wave_h > 5 or gusts > 60:
        safety = "DANGEROUS — do not enter the water"
    elif warnings:
        safety = "CAUTION — check local conditions and your skill level"
    else:
        safety = "Generally safe — normal precautions apply"

    if 1 <= wave_h <= 3 and swell_period >= 8 and wind < 25:
        surf_quality = "Good — clean conditions"
    elif wave_h < 0.5:
        surf_quality = "Flat — not worth paddling out"
    elif wind > 30:
        surf_quality = "Choppy — wind is ruining the waves"
    else:
        surf_quality = "Fair"

    return {
        "location": f"{geo['name']}, {geo['country']}",
        "current": {
            "wave_height_m": wave_h,
            "swell_height_m": swell_h,
            "swell_period_s": swell_period,
            "wave_direction_deg": current_marine.get("wave_direction", 0),
            "wind_kmh": wind,
            "wind_gusts_kmh": gusts,
            "air_temp_c": current_weather["temperature_2m"],
        },
        "three_day_max_wave_m": marine.get("daily", {}).get("wave_height_max", []),
        "surf_quality": surf_quality,
        "safety": safety,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Tool 3: Garden watering advisor
# ---------------------------------------------------------------------------

@mcp.tool()
@validate(city=lambda v: check_prompt_injection(v) or Validator.length(v, max_len=200))
async def garden_watering_advisor(
    city: Annotated[str, Field(description="City name (e.g. 'Austin', 'Melbourne', 'Nairobi')")],
) -> dict:
    """Advise whether to water your garden based on soil moisture,
    evapotranspiration, and upcoming rain.

    Uses the FAO-56 Penman-Monteith reference evapotranspiration (ET0)
    to estimate how much water your soil is losing, and cross-references
    it with precipitation forecasts and current soil moisture readings.
    """
    geo = await _geocode(city)
    lat, lon = geo["latitude"], geo["longitude"]

    data = await _http.get(WEATHER_API, params={
        "latitude": lat, "longitude": lon,
        "hourly": "soil_moisture_0_to_1cm,soil_moisture_1_to_3cm,"
                  "et0_fao_evapotranspiration",
        "daily": "precipitation_sum,precipitation_probability_max,"
                 "temperature_2m_max,temperature_2m_min,"
                 "et0_fao_evapotranspiration",
        "timezone": "auto",
        "forecast_days": 5,
    })

    daily = data["daily"]

    today_rain = daily["precipitation_sum"][0]
    today_rain_pct = daily["precipitation_probability_max"][0]
    today_et0 = daily["et0_fao_evapotranspiration"][0]
    today_tmax = daily["temperature_2m_max"][0]

    rain_3d = sum(daily["precipitation_sum"][:3])
    et0_3d = sum(daily["et0_fao_evapotranspiration"][:3])

    surface_moisture = None
    for val in reversed(data["hourly"]["soil_moisture_0_to_1cm"]):
        if val is not None:
            surface_moisture = val
            break

    reasons = []
    should_water = False

    if surface_moisture is not None and surface_moisture < 0.15:
        should_water = True
        reasons.append(
            f"Surface soil moisture is low ({surface_moisture:.2f} m³/m³)"
        )

    if today_et0 > 4.0:
        should_water = True
        reasons.append(
            f"High evapotranspiration today ({today_et0:.1f} mm) — "
            "plants are losing water fast"
        )

    if rain_3d > 10:
        should_water = False
        reasons.append(
            f"Significant rain expected in next 3 days ({rain_3d:.1f} mm)"
        )
    elif today_rain_pct > 70:
        reasons.append(
            f"Rain likely today ({today_rain_pct}% chance) — "
            "wait and reassess tonight"
        )
        should_water = False

    if today_tmax > 35:
        reasons.append(
            "Very hot day — if you water, do it in early morning or evening "
            "to reduce evaporation"
        )

    if not reasons:
        reasons.append("Conditions are moderate — water if soil feels dry")

    return {
        "location": f"{geo['name']}, {geo['country']}",
        "should_water": should_water,
        "recommendation": "Water your garden" if should_water else "Skip watering",
        "reasons": reasons,
        "data": {
            "surface_soil_moisture_m3m3": surface_moisture,
            "today_evapotranspiration_mm": today_et0,
            "today_rain_mm": today_rain,
            "today_rain_probability_pct": today_rain_pct,
            "today_high_c": today_tmax,
            "three_day_rain_total_mm": rain_3d,
            "three_day_et0_total_mm": et0_3d,
        },
        "five_day_forecast": {
            "dates": daily["time"],
            "rain_mm": daily["precipitation_sum"],
            "high_c": daily["temperature_2m_max"],
            "low_c": daily["temperature_2m_min"],
            "et0_mm": daily["et0_fao_evapotranspiration"],
        },
    }


def main():
    """Run the MCP server."""
    # Default to HTTP transport for server deployments.
    transport = os.getenv("MCP_TRANSPORT", "streamable-http")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
