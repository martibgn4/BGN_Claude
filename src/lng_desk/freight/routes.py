"""Registry of voyage routes used by the desk.

Keyed by (origin, destination) strings that match what `Cargo.origin` and
`DestinationOption.name` carry. Adding a route is a one-line registry update.
"""
from .voyage import VoyageRoute, SABINE_TO_NWE, SABINE_TO_JAPAN_PANAMA

# Additional preset routes can be added below as the desk's coverage grows.
RAS_LAFFAN_TO_JAPAN = VoyageRoute(name="Ras Laffan -> Japan", days_laden=20, days_ballast=20)
RAS_LAFFAN_TO_NWE   = VoyageRoute(name="Ras Laffan -> NWE",   days_laden=16, days_ballast=16)
GORGON_TO_JAPAN     = VoyageRoute(name="Gorgon -> Japan",     days_laden=14, days_ballast=14)

ROUTES: dict[tuple[str, str], VoyageRoute] = {
    ("Sabine Pass", "NWE"):   SABINE_TO_NWE,
    ("Sabine Pass", "Asia"):  SABINE_TO_JAPAN_PANAMA,   # default JKM-pegged destination
    ("Sabine Pass", "Japan"): SABINE_TO_JAPAN_PANAMA,
    ("Ras Laffan",  "Japan"): RAS_LAFFAN_TO_JAPAN,
    ("Ras Laffan",  "NWE"):   RAS_LAFFAN_TO_NWE,
    ("Gorgon",      "Japan"): GORGON_TO_JAPAN,
}


def get_route(origin: str, destination: str) -> VoyageRoute:
    try:
        return ROUTES[(origin, destination)]
    except KeyError as e:
        raise KeyError(
            f"No route registered for {origin} -> {destination}. "
            f"Add to lng_desk.freight.routes.ROUTES."
        ) from e
