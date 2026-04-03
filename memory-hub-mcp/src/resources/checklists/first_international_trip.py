"""Travel checklist for first-time international travelers."""

from ...core.app import mcp


@mcp.resource(
    "travel-checklists://first-international-trip",
    mime_type="text/markdown",
    description="Comprehensive checklist for first-time international travelers",
)
def first_international_trip_checklist() -> str:
    """Template checklist for inexperienced international travelers."""
    return """# First International Trip Checklist

## Pre-Booking (Research Phase)
- [ ] Check passport validity (needs 6+ months for most countries)
- [ ] Research visa requirements for destination
- [ ] Compare flight prices and book
- [ ] Book accommodation with free cancellation initially
- [ ] Check vaccination requirements
- [ ] Review travel insurance options

## 6 Weeks Out
- [ ] Apply for visa if required
- [ ] Get required vaccinations
- [ ] Purchase travel insurance
- [ ] Notify bank and credit card companies of travel dates
- [ ] Confirm passport is valid
- [ ] Make copies of important documents

## 2 Weeks Out
- [ ] Check-in for flights online (if available)
- [ ] Download offline maps for destination
- [ ] Research local emergency numbers
- [ ] Learn basic phrases in local language
- [ ] Confirm hotel reservations
- [ ] Check weather forecast and pack accordingly

## 1 Week Out
- [ ] Arrange airport transportation
- [ ] Hold mail or arrange for pickup
- [ ] Pay bills that will come due while away
- [ ] Charge all electronics
- [ ] Get local currency or notify bank of ATM usage

## Day Before Departure
- [ ] Reconfirm flight times
- [ ] Print boarding passes and hotel confirmations
- [ ] Pack carry-on with essentials
- [ ] Set away message on email
- [ ] Double-check passport and tickets

## Day of Departure
- [ ] Arrive at airport 3 hours early for international flights
- [ ] Keep passport and boarding pass accessible
- [ ] Keep medications in carry-on
- [ ] Stay hydrated during flight
"""
