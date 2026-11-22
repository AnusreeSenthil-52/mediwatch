"""
Block 5b - Look ahead (the new part).

1. Estimate how ill the patient is right now from the readings.
2. Estimate how fast that is changing (trend over the last minute).
3. Build a "digital twin" (a copy of the patient model) with those numbers.
4. Run the twin forward for each of three options:
      do_nothing - no action
      wait       - check again later, act after `wait_option_s` if needed
      help_now   - oxygen + nurse call immediately
5. Score each future with NEWS2 and pick the cheapest option.
"""
from statistics import mean

from .news2 import news2
from .patient import (BED_RAISED_RR_DROP, OXYGEN_SPO2_BOOST, POPULATION_BASELINE,
                      SLOPE, PatientModel)

OPTIONS = ["do_nothing", "wait", "help_now"]


def estimate_severity(v, oxygen_on, bed_raised):
    """Invert the patient model: which severity would explain these vitals?"""
    v = dict(v)
    if oxygen_on:
        v["spo2"] -= OXYGEN_SPO2_BOOST
    if bed_raised:
        v["rr"] += BED_RAISED_RR_DROP
    guesses = [(v[k] - POPULATION_BASELINE[k]) / SLOPE[k] for k in SLOPE]
    return min(1.0, max(0.0, mean(guesses)))


def trend(points):
    """Least-squares slope of (t, y) points."""
    n = len(points)
    mt = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    num = sum((t - mt) * (y - my) for t, y in points)
    den = sum((t - mt) ** 2 for t, _ in points) or 1.0
    return my, mt, num / den


def danger_penalty(score, rules):
    """Cost of ONE MINUTE spent at this score. The danger zone costs much more."""
    if score >= rules["emergency_threshold"]:
        return rules["cost_per_min"]["danger"]
    if score >= rules["predict_danger_score"]:
        return rules["cost_per_min"]["warning"]
    return 0.0


def simulate(option, s0, drift, oxygen_on, bed_raised, care, rules, step=5):
    twin = PatientModel({"start_severity": s0, "drift_per_s": drift}, care, personal_variation=False)
    twin.oxygen, twin.bed_raised = oxygen_on, bed_raised
    horizon = rules["predict_horizon_s"]
    act_at = {"do_nothing": None, "wait": rules["wait_option_s"], "help_now": 0}[option]
    penalty, scores, acted = 0.0, [], False
    for t in range(0, horizon + 1, step):
        if act_at is not None and not acted and t >= act_at:
            twin.oxygen = True
            twin.call_help("nurse")
            acted = True
        v = twin.vitals()
        v["on_oxygen"] = False              # judge physiology, not the oxygen point itself
        score = news2(v)[0]
        scores.append((t, score))
        penalty += danger_penalty(score, rules) * step / 60
        twin.step(step)
    return penalty, scores


def choose_by_time(danger_in_s, rules):
    """Pick the action from how soon danger is predicted (seconds from now).

    danger_in_s <= help_now_within_s            -> help_now   (danger is close: act immediately)
    help_now_within_s < danger_in_s <= no_action_beyond_s -> wait  (danger is coming: check again)
    danger_in_s >  no_action_beyond_s (or none) -> do_nothing (very far away: no action yet)
    The option costs are still calculated and shown for information.
    """
    if danger_in_s is None:
        return "do_nothing"
    if danger_in_s <= rules.get("help_now_within_s", 60):
        return "help_now"
    if danger_in_s <= rules.get("no_action_beyond_s", 180):
        return "wait"
    return "do_nothing"


def look_ahead(history, oxygen_on, bed_raised, care, rules):
    """
    history: list of (t, vitals_dict) for the last `predict_history_s` seconds.
    Returns a dict that the engine logs and the dashboard shows.
    """
    pts = [(t, estimate_severity(v, oxygen_on, bed_raised)) for t, v in history]
    s_mean, t_mean, slope = trend(pts)
    s_now = min(1.0, max(0.0, s_mean + slope * (pts[-1][0] - t_mean)))

    # convert observed slope back into the model's "drift" (see PatientModel.step)
    drift = slope / ((1 + 2 * s_now) * (0.6 if oxygen_on else 1.0))
    drift = max(0.0, drift)

    results = {}
    for option in OPTIONS:
        penalty, scores = simulate(option, s_now, drift, oxygen_on, bed_raised, care, rules)
        results[option] = {"penalty": penalty, "cost": penalty + rules["action_cost"][option],
                           "scores": scores}

    nothing = results["do_nothing"]["scores"]
    max_score = max(s for _, s in nothing)
    danger_at = next((t for t, s in nothing if s >= rules["predict_danger_score"]), None)
    heading = danger_at is not None
    choice = choose_by_time(danger_at, rules) if heading else "do_nothing"

    return {
        "severity_estimate": round(s_now, 3),
        "trend_per_min": round(slope * 60, 4),
        "predicted_max_score": max_score,
        "danger_in_s": danger_at,
        "heading_for_danger": heading,
        "choice": choice,
        "costs": {o: round(results[o]["cost"], 2) for o in OPTIONS},
    }
