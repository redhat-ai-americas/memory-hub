"""Emergency protocol for lost or stolen passport."""

from ...core.app import mcp


@mcp.resource(
    "emergency-protocols://passport-lost",
    mime_type="text/markdown",
    description="Step-by-step emergency response for lost or stolen passport",
)
def passport_lost_protocol() -> str:
    """Immediate steps and procedures when passport is lost or stolen abroad."""
    return """# Lost or Stolen Passport Protocol

## Immediate Steps (First 24 Hours)

### 1. Report to Local Police
- [ ] Go to nearest police station
- [ ] File a police report
- [ ] Get a copy of the report (required for embassy)
- [ ] Note the report number and officer's name

### 2. Contact Your Embassy/Consulate
**Find your embassy:**
- Use the U.S. Embassy website or call the 24/7 hotline
- Have your citizenship proof ready (driver's license, birth certificate copy)

**What to bring:**
- Police report
- Passport photos (2 required)
- Proof of citizenship
- Travel itinerary
- Government-issued ID

### 3. Apply for Emergency Travel Document
- Fill out Form DS-64 (Statement Regarding Lost or Stolen Passport)
- Fill out Form DS-11 (Application for U.S. Passport)
- Pay emergency passport fee (typically $150-200)
- Processing time: Usually same day or next business day

## Who to Contact

### U.S. Citizens
- **24/7 Hotline:** 1-888-407-4747 (from U.S.) or +1-202-501-4444 (from abroad)
- **Find Embassy:** https://www.usembassy.gov/

### Other Nationalities
- Contact your country's embassy or consulate immediately
- Most countries have 24/7 emergency services for citizens abroad

## Follow-Up Actions

### After Getting Emergency Document
- [ ] Keep emergency passport/document secure
- [ ] Apply for full passport replacement when home
- [ ] Report to your credit monitoring service (if passport had personal info)
- [ ] Update travel insurance company
- [ ] Document all expenses for insurance claim

### Upon Return Home
- [ ] Apply for new passport immediately
- [ ] Report to local passport office about theft
- [ ] Monitor for identity theft
- [ ] Update passport number with airlines, hotels, etc.

## Prevention Tips for Future Travel
- Keep passport in hotel safe when not needed
- Carry a color copy separately from original
- Store digital copy in secure cloud storage
- Use RFID-blocking passport holder
- Never leave passport in checked luggage
- Photograph all travel documents before trip
- Share copies with trusted family member at home
"""
