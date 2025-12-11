import time
from typing import Dict, Any, List

from django.db import transaction

from simulator.models import LandUse, RenewableData, VerbrauchData
from simulator.verbrauch_recalculator import recalc_all_verbrauch
from simulator.signals import recalculate_ws_data


def recalc_all_renewables_full() -> int:
    """
    Recalculate all non-fixed RenewableData items in a single pass using
    fresh LandUse and Verbrauch lookups. Uses in-memory lookups to avoid
    repeated database reads and suppresses downstream Verbrauch recalc to
    keep this step bounded.
    """
    dependent_items = RenewableData.objects.filter(
        formula__isnull=False,
    ).order_by("code")

    status_lookup: Dict[str, float] = {}
    target_lookup: Dict[str, float] = {}

    # LandUse values with LandUse_ prefix to match formulas
    # Strip LU_ prefix from codes since formulas use numeric codes (e.g., "1.1" not "LU_1.1")
    for lu in LandUse.objects.all():
        # Convert LU_1.1 -> LandUse_1.1, LU_2.1 -> LandUse_2.1, etc.
        clean_code = lu.code.replace('LU_', '') if lu.code.startswith('LU_') else lu.code
        key = f"LandUse_{clean_code}"
        if lu.status_ha is not None:
            status_lookup[key] = float(lu.status_ha)
        if lu.target_ha is not None:
            target_lookup[key] = float(lu.target_ha)

    # Verbrauch values
    verbrauch_status = {}
    verbrauch_target = {}
    for v in VerbrauchData.objects.all():
        if v.status is not None:
            verbrauch_status[v.code] = float(v.status)
        if v.ziel is not None:
            verbrauch_target[v.code] = float(v.ziel)

    # Existing Renewable values to seed lookups
    for item in RenewableData.objects.all():
        if item.status_value is not None:
            status_lookup[item.code] = float(item.status_value)
        if item.target_value is not None:
            target_lookup[item.code] = float(item.target_value)

    updated_count = 0
    for item in dependent_items:
        try:
            calc_status, calc_target = item.get_calculated_values(
                _cache={},
                status_lookup=status_lookup,
                target_lookup=target_lookup,
            )
        except Exception:
            calc_status, calc_target = None, None

        # Special case: status for 9.2.1.3 is defined as zero (no status-side supply)
        if item.code == "9.2.1.3":
            calc_status = 0

        def manual_eval(formula: str, use_target: bool):
            expr = formula or ""

            def repl(match):
                token = match.group(0)
                if token.startswith("LandUse_"):
                    return str(target_lookup.get(token, 0) if use_target else status_lookup.get(token, 0))
                if token.startswith("VerbrauchData_"):
                    vcode = token.replace("VerbrauchData_", "")
                    return str(verbrauch_target.get(vcode, 0) if use_target else verbrauch_status.get(vcode, 0))
                # Renewable codes keyed without prefix
                return str(target_lookup.get(token, 0) if use_target else status_lookup.get(token, 0))

            import re

            expr = re.sub(r"LandUse_[A-Za-z0-9\._]+|VerbrauchData_[\d\.]+|\d+(?:\.\d+)*", repl, expr)
            try:
                return eval(expr, {"__builtins__": {}})
            except Exception:
                return None

        if calc_status is None and item.formula:
            calc_status = manual_eval(item.formula, use_target=False)
        if calc_target is None and item.formula:
            calc_target = manual_eval(item.formula, use_target=True)

        values_changed = False
        if calc_status is not None and item.status_value != calc_status:
            item.status_value = calc_status
            values_changed = True
        if calc_target is not None and item.target_value != calc_target:
            item.target_value = calc_target
            values_changed = True

        if values_changed:
            item.save(skip_cascade=True, skip_verbrauch_recalc=True)
            status_lookup[item.code] = item.status_value
            target_lookup[item.code] = item.target_value
            updated_count += 1

    return updated_count


def run_full_recalc() -> Dict[str, Any]:
    """
    Centralized heavy recalculation invoked explicitly (e.g., from UI).
    Steps:
    - recalc all renewables once
    - recalc all Verbrauch rollups once
    - recalc WS data once
    Returns summary with timing and counts.
    """
    start = time.perf_counter()
    with transaction.atomic():
        # Recalculate renewable dependents for all LandUse entries first
        lu_updates = 0
        for lu in LandUse.objects.all():
            before = RenewableData.objects.count()
            lu._recalculate_renewable_dependents()
            after = RenewableData.objects.count()
            lu_updates += max(after - before, 0)

        renewables_updated = recalc_all_renewables_full()
        verbrauch_updated_codes: List[str] = recalc_all_verbrauch(trigger_code="manual")
        try:
            from simulator.renewable_recalc import recalc_renewables_for_verbrauch

            updated_from_verbrauch = 0
            for code in VerbrauchData.objects.values_list("code", flat=True):
                updated_codes = recalc_renewables_for_verbrauch(code)
                updated_from_verbrauch += len(updated_codes)
        except Exception:
            updated_from_verbrauch = 0
        recalculate_ws_data()

    duration_ms = int((time.perf_counter() - start) * 1000)
    return {
        "duration_ms": duration_ms,
        "renewables_updated": renewables_updated,
        "verbrauch_updated": len(verbrauch_updated_codes),
        "renewables_from_verbrauch": updated_from_verbrauch,
        "landuse_driven_updates": lu_updates,
    }
