"""
Bilanz (Balance Sheet) Calculation Engine

This module handles all calculations for the Bilanz diagram, which compares:
- Supply (Aktiva): Renewable + Fossil energy sources
- Demand (Passiva): Energy consumption by sector

All data comes dynamically from RenewableData and VerbrauchData models.
No hardcoded values.
"""

from django.apps import apps


def get_renewable_value(code, use_target=True):
    """
    Get renewable energy value from RenewableData model.
    
    Args:
        code: RenewableData code (e.g., '10.2' for renewable electricity)
        use_target: If True, returns target_value; if False, returns status_value
        
    Returns:
        float: The value, or 0 if not found
    """
    try:
        RenewableData = apps.get_model('simulator', 'RenewableData')
        renewable = RenewableData.objects.get(code=code)
        
        # Use calculated values if available
        status, target = renewable.get_calculated_values()
        
        if use_target:
            return target if target is not None else (renewable.target_value or 0)
        else:
            return status if status is not None else (renewable.status_value or 0)
    except Exception as e:
        print(f"Warning: Could not get renewable value for code {code}: {e}")
        return 0


def get_renewable_raw(code, field="target"):
    """
    Get raw stored renewable value (status_value/target_value) without recalculation.
    """
    try:
        RenewableData = apps.get_model('simulator', 'RenewableData')
        renewable = RenewableData.objects.get(code=code)
        if field == "target":
            return renewable.target_value or 0
        return renewable.status_value or 0
    except Exception as e:
        print(f"Warning: Could not get raw renewable value for code {code}: {e}")
        return 0


def get_verbrauch_value(code, use_ziel=True):
    """
    Get consumption value from VerbrauchData model.
    
    Args:
        code: VerbrauchData code (e.g., '1.4' for KLIK electricity)
        use_ziel: If True, returns ziel; if False, returns status
        
    Returns:
        float: The value, or 0 if not found
    """
    try:
        VerbrauchData = apps.get_model('simulator', 'VerbrauchData')
        verbrauch = VerbrauchData.objects.get(code=code)
        
        if use_ziel:
            return verbrauch.ziel or 0
        else:
            return verbrauch.status or 0
    except Exception as e:
        print(f"Warning: Could not get verbrauch value for code {code}: {e}")
        return 0


def calculate_bilanz_data():
    """
    Calculate all bilanz (balance sheet) data dynamically from RenewableData and VerbrauchData.
    
    Returns:
        dict: Complete bilanz data structure with all categories
    """
    # Ensure Verbrauch rollups are current before reading
    try:
        from simulator.verbrauch_recalculator import recalc_all_verbrauch
        recalc_all_verbrauch(trigger_code="bilanz_view")
    except Exception as exc:  # pragma: no cover - defensive guard
        print(f"Warning: Verbrauch recalculation before bilanz failed: {exc}")
    
    # ============================================================================
    # SECTION 1: VERBRAUCH STROM (Electricity Consumption)
    # ============================================================================
    
    # Get electricity consumption by sector (targets from VerbrauchData)
    klik_strom_s = get_verbrauch_value('1.4', use_ziel=False)  # Endverbrauch Strom KLIK gesamt (status)
    klik_strom_t = get_verbrauch_value('1.4', use_ziel=True)   # Endverbrauch Strom KLIK gesamt (target)
    
    gw_strom_s = get_verbrauch_value('2.10', use_ziel=False)   # Endenergieverbrauch GW gesamt (status)
    gw_strom_t = get_verbrauch_value('2.10', use_ziel=True)    # Endenergieverbrauch GW gesamt (target)
    
    pw_strom_s = get_verbrauch_value('3.7', use_ziel=False)    # Endenergieverbrauch PW gesamt (status)
    pw_strom_t = get_verbrauch_value('3.7', use_ziel=True)     # Endenergieverbrauch PW gesamt (target)
    
    mobile_strom_s = get_verbrauch_value('4.3.1', use_ziel=False)  # Mobile Anwendungen gesamt (status)
    mobile_strom_t = get_verbrauch_value('4.3.1', use_ziel=True)   # Mobile Anwendungen gesamt (target)
    
    # Total electricity demand
    total_strom_s = klik_strom_s + gw_strom_s + pw_strom_s + mobile_strom_s
    total_strom_t = klik_strom_t + gw_strom_t + pw_strom_t + mobile_strom_t
    
    # Get renewable electricity by sector from RenewableData targets
    # Use raw stored values to mirror Renewable Energy page targets/status
    klik_ren_s = get_renewable_raw('10.3', field="status")
    klik_ren_t = get_renewable_raw('10.3', field="target")
    gw_ren_s = get_renewable_raw('10.4', field="status")
    gw_ren_t = get_renewable_raw('10.4', field="target")
    pw_ren_s = get_renewable_raw('10.5', field="status")
    pw_ren_t = get_renewable_raw('10.5', field="target")
    mobile_ren_s = get_renewable_raw('10.6', field="status")
    mobile_ren_t = get_renewable_raw('10.6', field="target")

    strom_ren_s = klik_ren_s + gw_ren_s + pw_ren_s + mobile_ren_s
    strom_ren_t = klik_ren_t + gw_ren_t + pw_ren_t + mobile_ren_t
    
    # Calculate fossil electricity (per sector and totals)
    strom_fossil_k = max(0, klik_strom_s - klik_ren_s)
    strom_fossil_gw = max(0, gw_strom_s - gw_ren_s)
    strom_fossil_pw = max(0, pw_strom_s - pw_ren_s)
    strom_fossil_m = max(0, mobile_strom_s - mobile_ren_s)
    strom_fossil_s = strom_fossil_k + strom_fossil_gw + strom_fossil_pw + strom_fossil_m

    strom_fossil_k_t = max(0, klik_strom_t - klik_ren_t)
    strom_fossil_gw_t = max(0, gw_strom_t - gw_ren_t)
    strom_fossil_pw_t = max(0, pw_strom_t - pw_ren_t)
    strom_fossil_m_t = max(0, mobile_strom_t - mobile_ren_t)
    strom_fossil_t = strom_fossil_k_t + strom_fossil_gw_t + strom_fossil_pw_t + strom_fossil_m_t
    
    # Build electricity data structures
    verbrauch_strom = {
        'status': {
            'kraft_licht': klik_strom_s,
            'gebaeudewaerme': gw_strom_s,
            'prozesswaerme': pw_strom_s,
            'mobile': mobile_strom_s,
            'gesamt': total_strom_s,
        },
        'ziel': {
            'kraft_licht': klik_strom_t,
            'gebaeudewaerme': gw_strom_t,
            'prozesswaerme': pw_strom_t,
            'mobile': mobile_strom_t,
            'gesamt': total_strom_t,
        }
    }
    
    # Renewable electricity by sector (direct)
    verbrauch_strom_renewable = {
        'status': {
            'kraft_licht': klik_ren_s,
            'gebaeudewaerme': gw_ren_s,
            'prozesswaerme': pw_ren_s,
            'mobile': mobile_ren_s,
            'gesamt': strom_ren_s,
        },
        'ziel': {
            'kraft_licht': klik_ren_t,
            'gebaeudewaerme': gw_ren_t,
            'prozesswaerme': pw_ren_t,
            'mobile': mobile_ren_t,
            'gesamt': strom_ren_t,
        }
    }
    
    # Fossil electricity by sector (demand minus renewable)
    verbrauch_strom_fossil = {
        'status': {
            'kraft_licht': strom_fossil_k,
            'gebaeudewaerme': strom_fossil_gw,
            'prozesswaerme': strom_fossil_pw,
            'mobile': strom_fossil_m,
            'gesamt': strom_fossil_s,
        },
        'ziel': {
            'kraft_licht': strom_fossil_k_t,
            'gebaeudewaerme': strom_fossil_gw_t,
            'prozesswaerme': strom_fossil_pw_t,
            'mobile': strom_fossil_m_t,
            'gesamt': strom_fossil_t,
        }
    }
    
    # ============================================================================
    # SECTION 2: VERBRAUCH BRENNSTOFFE (Fuel Consumption)
    # ============================================================================
    
    # Get fuel consumption by sector from VerbrauchData
    gw_fuels_s = get_verbrauch_value('2.7.0', use_ziel=False)  # Gebäudewärme fuels status
    gw_fuels_t = get_verbrauch_value('2.7.0', use_ziel=True)   # Gebäudewärme fuels target
    
    pw_fuels_s = get_verbrauch_value('3.4.0', use_ziel=False)  # Prozesswärme fuels status
    pw_fuels_t = get_verbrauch_value('3.4.0', use_ziel=True)   # Prozesswärme fuels target
    
    mobile_fuels_s = get_verbrauch_value('4.3.2', use_ziel=False)  # Mobile fuels status
    mobile_fuels_t = get_verbrauch_value('4.3.2', use_ziel=True)   # Mobile fuels target
    
    # Get mobile fuel breakdown (for distribution analysis)
    mobile_gas_s = get_verbrauch_value('4.3.4', use_ziel=False)  # Mobile gaseous
    mobile_gas_t = get_verbrauch_value('4.3.4', use_ziel=True)
    
    # Total fuel consumption
    total_fuels_s = gw_fuels_s + pw_fuels_s + mobile_fuels_s
    total_fuels_t = gw_fuels_t + pw_fuels_t + mobile_fuels_t
    
    # Get renewable fuels from RenewableData (Section 10.7)
    fuels_ren_s = get_renewable_value('10.7', use_target=False)  # Renewable fuels
    fuels_ren_t = get_renewable_value('10.7', use_target=True)
    
    # Calculate fossil fuels
    fuels_fossil_s = max(0, total_fuels_s - fuels_ren_s)
    fuels_fossil_t = max(0, total_fuels_t - fuels_ren_t)
    
    # Build fuel data structures
    verbrauch_fuels = {
        'status': {
            'kraft_licht': 0,  # KLIK uses only electricity, no fuels
            'gebaeudewaerme': gw_fuels_s,
            'prozesswaerme': pw_fuels_s,
            'mobile': mobile_fuels_s,
            'gesamt': total_fuels_s,
        },
        'ziel': {
            'kraft_licht': 0,
            'gebaeudewaerme': gw_fuels_t,
            'prozesswaerme': pw_fuels_t,
            'mobile': mobile_fuels_t,
            'gesamt': total_fuels_t,
        }
    }
    
    # Proportional renewable/fossil distribution
    verbrauch_fuels_renewable = {
        'status': {
            'kraft_licht': 0,
            'gebaeudewaerme': gw_fuels_s * (fuels_ren_s / total_fuels_s if total_fuels_s > 0 else 0),
            'prozesswaerme': pw_fuels_s * (fuels_ren_s / total_fuels_s if total_fuels_s > 0 else 0),
            'mobile': mobile_fuels_s * (fuels_ren_s / total_fuels_s if total_fuels_s > 0 else 0),
            'gesamt': fuels_ren_s,
        },
        'ziel': {
            'kraft_licht': 0,
            'gebaeudewaerme': gw_fuels_t * (fuels_ren_t / total_fuels_t if total_fuels_t > 0 else 1),
            'prozesswaerme': pw_fuels_t * (fuels_ren_t / total_fuels_t if total_fuels_t > 0 else 1),
            'mobile': mobile_fuels_t * (fuels_ren_t / total_fuels_t if total_fuels_t > 0 else 1),
            'gesamt': fuels_ren_t,
        }
    }
    
    verbrauch_fuels_fossil = {
        'status': {
            'kraft_licht': 0,
            'gebaeudewaerme': gw_fuels_s * (fuels_fossil_s / total_fuels_s if total_fuels_s > 0 else 0),
            'prozesswaerme': pw_fuels_s * (fuels_fossil_s / total_fuels_s if total_fuels_s > 0 else 0),
            'mobile': mobile_fuels_s * (fuels_fossil_s / total_fuels_s if total_fuels_s > 0 else 0),
            'gesamt': fuels_fossil_s,
        },
        'ziel': {
            'kraft_licht': 0,
            'gebaeudewaerme': gw_fuels_t * (fuels_fossil_t / total_fuels_t if total_fuels_t > 0 else 0),
            'prozesswaerme': pw_fuels_t * (fuels_fossil_t / total_fuels_t if total_fuels_t > 0 else 0),
            'mobile': mobile_fuels_t * (fuels_fossil_t / total_fuels_t if total_fuels_t > 0 else 0),
            'gesamt': fuels_fossil_t,
        }
    }
    
    # Fuel breakdown by type (gaseous, liquid, solid)
    # Distribution percentages based on typical energy mix
    fuels_breakdown = {
        'gaseous': {
            'status': gw_fuels_s * 0.55 + pw_fuels_s * 0.58 + mobile_gas_s,
            'ziel': gw_fuels_t * 0.55 + pw_fuels_t * 0.58 + mobile_gas_t,
        },
        'liquid': {
            'status': gw_fuels_s * 0.22 + pw_fuels_s * 0.07 + (mobile_fuels_s - mobile_gas_s),
            'ziel': gw_fuels_t * 0.22 + pw_fuels_t * 0.07 + (mobile_fuels_t - mobile_gas_t),
        },
        'solid': {
            'status': gw_fuels_s * 0.23 + pw_fuels_s * 0.35,
            'ziel': gw_fuels_t * 0.23 + pw_fuels_t * 0.35,
        },
    }
    
    # ============================================================================
    # SECTION 3: VERBRAUCH WÄRME (Heat Consumption)
    # ============================================================================
    
    # Get heat consumption by sector from VerbrauchData
    gw_heat_s = get_verbrauch_value('2.8.0', use_ziel=False)  # Gebäudewärme heat status
    gw_heat_t = get_verbrauch_value('2.8.0', use_ziel=True)   # Gebäudewärme heat target
    
    pw_heat_s = get_verbrauch_value('3.5.0', use_ziel=False)  # Prozesswärme heat status
    pw_heat_t = get_verbrauch_value('3.5.0', use_ziel=True)   # Prozesswärme heat target
    
    # Total heat consumption
    total_heat_s = gw_heat_s + pw_heat_s
    total_heat_t = gw_heat_t + pw_heat_t
    
    # Get renewable heat from RenewableData
    heat_ren_gw_s = get_renewable_value('10.4.2', use_target=False)  # Gebäudewärme renewable heat
    heat_ren_gw_t = get_renewable_value('10.4.2', use_target=True)
    
    heat_ren_pw_s = get_renewable_value('10.5.2', use_target=False)  # Prozesswärme renewable heat
    heat_ren_pw_t = get_renewable_value('10.5.2', use_target=True)
    
    total_heat_ren_s = heat_ren_gw_s + heat_ren_pw_s
    total_heat_ren_t = heat_ren_gw_t + heat_ren_pw_t
    
    # Calculate fossil heat
    heat_fossil_gw_s = max(0, gw_heat_s - heat_ren_gw_s)
    heat_fossil_gw_t = max(0, gw_heat_t - heat_ren_gw_t)
    
    heat_fossil_pw_s = max(0, pw_heat_s - heat_ren_pw_s)
    heat_fossil_pw_t = max(0, pw_heat_t - heat_ren_pw_t)
    
    # Build heat data structures
    verbrauch_heat = {
        'status': {
            'kraft_licht': 0,  # No direct heat for KLIK
            'gebaeudewaerme': gw_heat_s,
            'prozesswaerme': pw_heat_s,
            'mobile': 0,
            'gesamt': total_heat_s,
        },
        'ziel': {
            'kraft_licht': 0,
            'gebaeudewaerme': gw_heat_t,
            'prozesswaerme': pw_heat_t,
            'mobile': 0,
            'gesamt': total_heat_t,
        }
    }
    
    verbrauch_heat_renewable = {
        'status': {
            'kraft_licht': 0,
            'gebaeudewaerme': heat_ren_gw_s,
            'prozesswaerme': heat_ren_pw_s,
            'mobile': 0,
            'gesamt': total_heat_ren_s,
        },
        'ziel': {
            'kraft_licht': 0,
            'gebaeudewaerme': heat_ren_gw_t,
            'prozesswaerme': heat_ren_pw_t,
            'mobile': 0,
            'gesamt': total_heat_ren_t,
        }
    }
    
    verbrauch_heat_fossil = {
        'status': {
            'kraft_licht': 0,
            'gebaeudewaerme': heat_fossil_gw_s,
            'prozesswaerme': heat_fossil_pw_s,
            'mobile': 0,
            'gesamt': heat_fossil_gw_s + heat_fossil_pw_s,
        },
        'ziel': {
            'kraft_licht': 0,
            'gebaeudewaerme': heat_fossil_gw_t,
            'prozesswaerme': heat_fossil_pw_t,
            'mobile': 0,
            'gesamt': heat_fossil_gw_t + heat_fossil_pw_t,
        }
    }
    
    # Abwärme (Waste Heat) - get from RenewableData if available
    # TODO: Add appropriate RenewableData codes for waste heat when available
    verbrauch_heat_abwaerme = {
        'status': {
            'kraft_licht': 0,
            'gebaeudewaerme': 0,
            'prozesswaerme': 0,
            'mobile': 0,
            'gesamt': 0,
        },
        'ziel': {
            'kraft_licht': 0,
            'gebaeudewaerme': 0,
            'prozesswaerme': 0,
            'mobile': 0,
            'gesamt': 0,
        }
    }
    
    # ============================================================================
    # SECTION 4: VERBRAUCH GESAMT (Total Consumption)
    # ============================================================================
    
    # Use direct total codes from VerbrauchData - use same code for both status and ziel
    # The code is the same, but we pull from different columns (status vs ziel)
    
    # KLIK: Code 1 - status column for Status, ziel column for Ziel
    klik_total_s = get_verbrauch_value('1', use_ziel=False)      # Status column: 329,214
    klik_total_t = get_verbrauch_value('1', use_ziel=True)       # Ziel column
    
    # Gebäudewärme: Code 2.10 - status column for Status, ziel column for Ziel
    gw_total_s = get_verbrauch_value('2.10', use_ziel=False)     # Status column: 798,867
    gw_total_t = get_verbrauch_value('2.10', use_ziel=True)      # Ziel column: 663,397
    
    # Prozesswärme: Code 3.3 - status column for Status, ziel column for Ziel
    pw_total_s = get_verbrauch_value('3.7', use_ziel=False)      # Prozesswärme gesamt status
    pw_total_t = get_verbrauch_value('3.7', use_ziel=True)       # Prozesswärme gesamt ziel
    
    # Mobile: Code 4.3.1 - status column for Status, ziel column for Ziel
    mobile_total_s = get_verbrauch_value('4.3.1', use_ziel=False)  # Status column: 753,713
    mobile_total_t = get_verbrauch_value('4.3.1', use_ziel=True)   # Ziel column: 388,761
    
    # Total consumption by sector (using direct codes from same row, different columns)
    verbrauch_gesamt = {
        'status': {
            'kraft_licht': klik_total_s,
            'gebaeudewaerme': gw_total_s,
            'prozesswaerme': pw_total_s,
            'mobile': mobile_total_s,
            'gesamt': klik_total_s + gw_total_s + pw_total_s + mobile_total_s,
        },
        'ziel': {
            'kraft_licht': klik_total_t,
            'gebaeudewaerme': gw_total_t,
            'prozesswaerme': pw_total_t,
            'mobile': mobile_total_t,
            'gesamt': klik_total_t + gw_total_t + pw_total_t + mobile_total_t,
        }
    }

    # ============================================================================
    # SECTION 5: RENEWABLE BY SECTOR (direct RenewableData codes 10.3–10.6)
    # ============================================================================
    def safe_get_renewable(code: str, use_target: bool):
        try:
            return get_renewable_value(code, use_target=use_target)
        except Exception:
            return 0

    renewable_by_sector = {
        'status': {
            'kraft_licht': safe_get_renewable('10.3', use_target=False),
            'gebaeudewaerme': safe_get_renewable('10.4', use_target=False),
            'prozesswaerme': safe_get_renewable('10.5', use_target=False),
            'mobile': safe_get_renewable('10.6', use_target=False),
        },
        'ziel': {
            'kraft_licht': safe_get_renewable('10.3', use_target=True),
            'gebaeudewaerme': safe_get_renewable('10.4', use_target=True),
            'prozesswaerme': safe_get_renewable('10.5', use_target=True),
            'mobile': safe_get_renewable('10.6', use_target=True),
        },
    }
    renewable_by_sector['status']['gesamt'] = sum(renewable_by_sector['status'].values())
    renewable_by_sector['ziel']['gesamt'] = sum(renewable_by_sector['ziel'].values())

    # ============================================================================
    # SECTION 6: VERBRAUCH GESAMT FOSSIL (remaining after renewable by sector)
    # ============================================================================
    def residual(total_dict, ren_dict):
        return {
            'kraft_licht': max(0, total_dict['kraft_licht'] - ren_dict['kraft_licht']),
            'gebaeudewaerme': max(0, total_dict['gebaeudewaerme'] - ren_dict['gebaeudewaerme']),
            'prozesswaerme': max(0, total_dict['prozesswaerme'] - ren_dict['prozesswaerme']),
            'mobile': max(0, total_dict['mobile'] - ren_dict['mobile']),
        }

    verbrauch_gesamt_fossil = {
        'status': residual(verbrauch_gesamt['status'], renewable_by_sector['status']),
        'ziel': residual(verbrauch_gesamt['ziel'], renewable_by_sector['ziel']),
    }
    verbrauch_gesamt_fossil['status']['gesamt'] = sum(verbrauch_gesamt_fossil['status'].values())
    verbrauch_gesamt_fossil['ziel']['gesamt'] = sum(verbrauch_gesamt_fossil['ziel'].values())

    # ============================================================================
    # RETURN COMPLETE DATA STRUCTURE
    # ============================================================================

    return {
        'verbrauch_strom': verbrauch_strom,
        'verbrauch_strom_renewable': verbrauch_strom_renewable,
        'verbrauch_strom_fossil': verbrauch_strom_fossil,
        'verbrauch_fuels': verbrauch_fuels,
        'verbrauch_fuels_renewable': verbrauch_fuels_renewable,
        'verbrauch_fuels_fossil': verbrauch_fuels_fossil,
        'fuels_breakdown': fuels_breakdown,
        'verbrauch_heat': verbrauch_heat,
        'verbrauch_heat_renewable': verbrauch_heat_renewable,
        'verbrauch_heat_fossil': verbrauch_heat_fossil,
        'verbrauch_heat_abwaerme': verbrauch_heat_abwaerme,
        'verbrauch_gesamt': verbrauch_gesamt,
        'verbrauch_gesamt_fossil': verbrauch_gesamt_fossil,
        'erneuerbar': renewable_by_sector,
        'renewable_by_sector': renewable_by_sector,
    }
