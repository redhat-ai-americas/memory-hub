"""Country profile resource for Japan."""

from ...core.app import mcp


@mcp.resource(
    "country-profiles://JP",
    mime_type="application/json",
    description="Curated country profile for Japan with essential travel information",
)
def japan_profile() -> dict:
    """Essential information for travelers visiting Japan."""
    return {
        "country_code": "JP",
        "common_name": "Japan",
        "capital": "Tokyo",
        "emergency_numbers": {
            "police": "110",
            "ambulance": "119",
            "us_embassy": "+81-3-3224-5000",
        },
        "cultural_highlights": [
            "Cherry blossom season (March-April)",
            "Traditional temples and shrines",
            "Modern technology centers",
            "Unique cuisine and food culture",
        ],
        "safety_tips": [
            "Very safe country with low crime rates",
            "Earthquakes are common - know emergency procedures",
            "Public transportation is excellent and punctual",
            "Cash is still widely used despite being high-tech",
        ],
        "transportation_overview": "World-class public transportation with extensive train and subway networks. JR Pass recommended for tourists.",
        "connectivity": {
            "sim_cards": "Available at airports (Narita, Haneda)",
            "wifi": "Ubiquitous in cities, pocket WiFi rentals popular",
        },
    }
