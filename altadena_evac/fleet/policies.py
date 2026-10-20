"""The four AV dispatch policies (requirement 7), resolved to a flag set the
dispatcher consumes. Common dispatch rules stay identical across policies so a
comparison isolates the policy under study; only the fields below differ.

A. withdrawal        — stop accepting NEW pickups once a withdrawal trigger fires.
B. normal            — first-come, first-served; no vulnerability priority.
C. evac_priority     — prioritize carless + explicit assistance-need households.
D. adaptive_geofencing — evac_priority + forecast-based trip screening of BOTH
                         the pickup journey and the passenger journey; accepted
                         trips are reassessed when conditions change.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ResolvedPolicy:
    name: str
    priority: str = "fcfs"                 # fcfs | vulnerability_first
    priority_keys: list = field(default_factory=list)
    # geofencing screening
    screen_pickup: bool = False
    screen_passenger: bool = False
    use_forecast: bool = True
    reject_if_infeasible: bool = False
    # withdrawal
    is_withdrawal: bool = False
    withdrawal_trigger_type: str = ""
    withdrawal_trigger_value: float = 0.0
    onboard_rule: str = "complete_dropoff_at_safety"
    assigned_rule: str = "cancel_and_reoffer"
    retreat: str = "nearest_destination"
    retreat_changes: bool = False

    def request_sort_key(self, req):
        """Order pending requests. Lower sorts first (served earlier)."""
        if self.priority == "vulnerability_first":
            # carless first, then assistance need, then request time
            return (0 if req.no_vehicle else 1,
                    0 if req.assistance_need else 1,
                    req.request_time_s)
        return (req.request_time_s,)   # FCFS


def resolve_policy(name: str, fleet_cfg: dict) -> ResolvedPolicy:
    pol = fleet_cfg["policies"][name]
    rp = ResolvedPolicy(name=name)
    rp.priority = pol.get("priority", "fcfs")
    rp.priority_keys = pol.get("priority_keys", [])

    if name == "withdrawal":
        rp.is_withdrawal = True
        trig = pol.get("withdrawal_trigger", {})
        rp.withdrawal_trigger_type = trig.get("type", "forecast_front_within_m")
        rp.withdrawal_trigger_value = float(trig.get("value", 0.0))
        rp.onboard_rule = pol.get("onboard_passengers", "complete_dropoff_at_safety")
        rp.assigned_rule = pol.get("assigned_but_not_boarded", "cancel_and_reoffer")
        rp.retreat = pol.get("retreat", "nearest_destination")

    if name == "adaptive_geofencing":
        scr = pol.get("screening", {})
        rp.screen_pickup = bool(scr.get("check_pickup_journey", True))
        rp.screen_passenger = bool(scr.get("check_passenger_journey", True))
        rp.use_forecast = bool(scr.get("use_forecast", True))
        rp.reject_if_infeasible = bool(scr.get("reject_if_infeasible", True))
        rp.retreat_changes = bool(pol.get("retreat_changes", False))

    return rp
