"""SUMO/TraCI backend STUB — documents the alternative traffic engine.

The default engine is the in-process mesoscopic model (mesoscopic.py); see the
README "Why a custom traffic engine". SUMO 1.27 + TraCI is available in the dev
environment. A future port would:

  1. netconvert the OSM extract:
        netconvert --osm-files altadena.osm.xml -o altadena.net.xml \\
                   --geometry.remove --roundabouts.guess --ramps.guess \\
                   --junctions.join --tls.guess-signals
  2. generate trips/routes from the synthetic demand (origins -> destinations),
     writing a SUMO .rou.xml with one <vehicle> per vehicle trip and <person>
     ride stages for AV passengers.
  3. drive the sim through TraCI, stepping with traci.simulationStep(), using:
        traci.vehicle.add / traci.vehicle.changeTarget  (dispatch/reroute)
        traci.edge.setDisallowed / traci.edge.setMaxSpeed(0)  (hazard closures)
        traci.vehicle.getRoadID / getPosition  (forecast screening geometry)
        traci.simulation.getArrivedIDList  (arrivals)

This file intentionally raises on use so no silent half-backend exists.
"""
from __future__ import annotations


class SumoBackend:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "SUMO backend is a documented stub in v0.1. The default mesoscopic "
            "engine (altadena_evac.network.mesoscopic.MesoNetwork) is used. See "
            "this module's docstring for the intended TraCI port."
        )
