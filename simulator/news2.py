"""
Block 4 - Warning score.

NEWS2 (National Early Warning Score 2, Royal College of Physicians, 2017).
Uses SpO2 Scale 1 (the normal scale for patients without chronic
hypercapnic respiratory failure).

Input : dict with rr, spo2, on_oxygen, sbp, hr, consciousness, temp
Output: (total_score, risk_band, points_per_parameter)
"""


def score_rr(rr):
    rr = round(rr)
    if rr <= 8:
        return 3
    if rr <= 11:
        return 1
    if rr <= 20:
        return 0
    if rr <= 24:
        return 2
    return 3


def score_spo2(spo2):
    spo2 = round(spo2)
    if spo2 <= 91:
        return 3
    if spo2 <= 93:
        return 2
    if spo2 <= 95:
        return 1
    return 0


def score_oxygen(on_oxygen):
    return 2 if on_oxygen else 0


def score_sbp(sbp):
    sbp = round(sbp)
    if sbp <= 90:
        return 3
    if sbp <= 100:
        return 2
    if sbp <= 110:
        return 1
    if sbp <= 219:
        return 0
    return 3


def score_hr(hr):
    hr = round(hr)
    if hr <= 40:
        return 3
    if hr <= 50:
        return 1
    if hr <= 90:
        return 0
    if hr <= 110:
        return 1
    if hr <= 130:
        return 2
    return 3


def score_consciousness(level):
    # ACVPU: A = Alert scores 0; new Confusion, Voice, Pain, Unresponsive score 3
    return 0 if level == "A" else 3


def score_temp(temp):
    temp = round(temp, 1)
    if temp <= 35.0:
        return 3
    if temp <= 36.0:
        return 1
    if temp <= 38.0:
        return 0
    if temp <= 39.0:
        return 1
    return 2


def risk_band(total, parts):
    """Clinical response bands from the NEWS2 chart."""
    if total >= 7:
        return "high"          # red    - emergency response
    if total >= 5:
        return "medium"        # orange - urgent response
    if max(parts.values()) == 3:
        return "low-medium"    # yellow - a single parameter scored 3
    return "low"               # green


def news2(v):
    parts = {
        "rr": score_rr(v["rr"]),
        "spo2": score_spo2(v["spo2"]),
        "oxygen": score_oxygen(v.get("on_oxygen", False)),
        "sbp": score_sbp(v["sbp"]),
        "hr": score_hr(v["hr"]),
        "consciousness": score_consciousness(v["consciousness"]),
        "temp": score_temp(v["temp"]),
    }
    total = sum(parts.values())
    return total, risk_band(total, parts), parts


if __name__ == "__main__":
    # Quick self-test: run  python -m simulator.news2
    healthy = dict(rr=16, spo2=97, on_oxygen=False, sbp=125, hr=75, consciousness="A", temp=36.8)
    sick = dict(rr=26, spo2=90, on_oxygen=True, sbp=95, hr=125, consciousness="V", temp=39.4)
    print("healthy:", news2(healthy))   # expect 0, low
    print("sick   :", news2(sick))      # expect 3+3+2+2+2+3+2 = 17, high
