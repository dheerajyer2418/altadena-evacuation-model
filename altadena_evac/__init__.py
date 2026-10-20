"""Altadena wildfire evacuation agent-based model.

Subpackages
-----------
config      : YAML loading / merging
population  : Census importer, PUMS-donor synthesis, placement, agent records
network     : OSM -> routable mesoscopic network, routing, traffic engine
behavior    : evacuation timeline (awareness/prep/request/departure/arrival)
hazard      : time-dependent hazard ground-truth + forecast
fleet       : vehicle/AV agents, dispatch service, four AV policies
sim         : simulation engine and metrics
viz         : plots and maps
data        : external-data interfaces (Census, PUMS, INRIX)

Units are SI everywhere: seconds, meters, vehicles, people.
"""

__version__ = "0.1.0"
