from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import LandUse, RenewableData, VerbrauchData
from .ws_models import WSData


@receiver(post_save, sender=LandUse)
def update_renewable_calculations(sender, instance, created, **kwargs):
    """
    Automatically update renewable energy calculations when LandUse data changes
    """
    # Mapping of LandUse codes to renewable codes that depend on them
    landuse_to_renewable_mapping = {
        '1.1': ['1.1'],  # LandUse 1.1 affects Renewable 1.1 (Solare Dachflächen)
        '2.1': ['1.2'],  # LandUse 2.1 affects Renewable 1.2 (Solar Freiflächen)
    }
    
    # Check if this LandUse change affects any renewable entries
    if instance.code in landuse_to_renewable_mapping:
        affected_renewable_codes = landuse_to_renewable_mapping[instance.code]
        
        print(f"🔄 LandUse {instance.code} changed - updating dependent renewable entries")
        
        for renewable_code in affected_renewable_codes:
            try:
                # We don't need to update values since the view dynamically pulls from LandUse
                # But we can log the change or trigger cache clearing if needed
                renewable = RenewableData.objects.get(category='Solar', code=renewable_code)
                print(f"   ↳ Renewable {renewable.code} will show updated LandUse values")
                
                # You could add cache clearing here if you implement caching later
                # cache.delete(f'renewable_calculation_{renewable.code}')
                
            except RenewableData.DoesNotExist:
                print(f"   ⚠️ Renewable {renewable_code} not found")


@receiver(post_delete, sender=LandUse)
def handle_landuse_deletion(sender, instance, **kwargs):
    """
    Handle when LandUse data is deleted
    """
    landuse_to_renewable_mapping = {
        '1.1': ['1.1'],
        '2.1': ['1.2'],
    }
    
    if instance.code in landuse_to_renewable_mapping:
        affected_renewable_codes = landuse_to_renewable_mapping[instance.code]
        print(f"⚠️ LandUse {instance.code} deleted - renewable entries {affected_renewable_codes} will show empty values")


def compute_ws_diagram_reference():
    """
    Compute Annual Electricity (WS1) reference values used by WS recalculation.
    Returns a dict with the reference stromverbr_raumwaerm_korr_366 and the
    component totals needed for downstream percentage splits.
    """

    def get_renewable_target(code):
        try:
            renewable = RenewableData.objects.get(code=code)
            return float(renewable.target_value) if renewable.target_value is not None else 0
        except RenewableData.DoesNotExist:
            return 0

    # Prefer status_value when available (e.g., after WS balance), otherwise fallback to target_value
    def get_status_or_target(code):
        try:
            renewable = RenewableData.objects.get(code=code)
            if renewable.status_value is not None:
                return float(renewable.status_value)
            if renewable.target_value is not None:
                return float(renewable.target_value)
            return 0
        except RenewableData.DoesNotExist:
            return 0

    # For WS baseline, use renewable targets (LU-driven), not WS overrides
    pv_value = get_renewable_target('1.1.2.1.2') + get_renewable_target('1.2.1.2')
    wind_value = get_renewable_target('2.1.1.2.2') + get_renewable_target('2.2.1.2')
    hydro_value = get_renewable_target('3.1.1.2')
    bio_value = get_renewable_target('4.4.1')
    ely_power_to_gas = get_renewable_target('9.2.1.5.2')
    # Use status-or-target for N branches so WS baseline matches the annual diagram display
    n_output_branch = get_status_or_target('9.3.1')
    n_input_branch = get_status_or_target('9.3.4')

    total_generation = pv_value + wind_value + hydro_value
    remaining_after_ely = total_generation - ely_power_to_gas
    gas_storage = n_output_branch * 0.65
    t_value = gas_storage - 160
    m_total = pv_value + wind_value + hydro_value
    n_value = m_total - ely_power_to_gas
    n_to_right = n_value - n_input_branch - n_output_branch
    stromverbr_raumwaerm_korr_366 = (t_value * 0.585) + n_to_right + bio_value

    if total_generation > 0:
        percentage = remaining_after_ely / total_generation
        solarstrom_366 = pv_value * percentage
        windstrom_366 = wind_value * percentage
        sonst_kraft_konstant_366 = hydro_value * percentage
    else:
        solarstrom_366 = 0
        windstrom_366 = 0
        sonst_kraft_konstant_366 = 0

    # If WS row 366 exists, override N/Q/T inputs from WS to keep baseline aligned with diagram
    try:
        ws_366 = WSData.objects.get(tag_im_jahr=366)
        if ws_366.abregelung_z is not None:
            n_input_branch = ws_366.abregelung_z
        if ws_366.einspeich is not None:
            n_output_branch = ws_366.einspeich / 0.65 if ws_366.einspeich else 0
            gas_storage = n_output_branch * 0.65
        if ws_366.ausspeich_rueckverstr is not None:
            # Only T uses Ausspeich. Rückverstr.; U stays derived from Einspeich
            t_value = ws_366.ausspeich_rueckverstr * 0.585
    except WSData.DoesNotExist:
        pass

    return {
        "stromverbr_raumwaerm_korr_366": stromverbr_raumwaerm_korr_366,
        "pv_value": pv_value,
        "wind_value": wind_value,
        "hydro_value": hydro_value,
        "bio_value": bio_value,
        "ely_power_to_gas": ely_power_to_gas,
        "n_output_branch": n_output_branch,
        "n_input_branch": n_input_branch,
        "total_generation": total_generation,
        "remaining_after_ely": remaining_after_ely,
        "solarstrom_366": solarstrom_366,
        "windstrom_366": windstrom_366,
        "sonst_kraft_konstant_366": sonst_kraft_konstant_366,
    }


def recalculate_ws_data(stromverbr_override=None, use_diagram_reference=True):
    """
    Recalculate all WS data based on Annual Electricity and Verbrauch data.
    If stromverbr_override is provided AND use_diagram_reference is False,
    that override is used instead of recomputing the diagram reference. This
    lets a GoalSeek loop adjust Stromverbr. Raumw.korr. (row 366) without
    re-deriving it from the diagram each iteration.
    """

    # Get reference value for davon_raumw_korr from WS diagram
    # This is the reference value used to calculate daily values
    try:
        verbrauch_292 = VerbrauchData.objects.get(code='2.9.2')
        verbrauch_24 = VerbrauchData.objects.get(code='2.4')
        davon_raumw_korr_366 = verbrauch_292.ziel * (verbrauch_24.ziel / 100)
    except VerbrauchData.DoesNotExist:
        davon_raumw_korr_366 = 0

    diagram = compute_ws_diagram_reference()
    pv_value = diagram["pv_value"]
    wind_value = diagram["wind_value"]
    hydro_value = diagram["hydro_value"]
    bio_value = diagram["bio_value"]
    solarstrom_366 = diagram["solarstrom_366"]
    windstrom_366 = diagram["windstrom_366"]
    sonst_kraft_konstant_366 = diagram["sonst_kraft_konstant_366"]

    stromverbr_raumwaerm_korr_366 = diagram["stromverbr_raumwaerm_korr_366"]
    if stromverbr_override is not None and not use_diagram_reference:
        stromverbr_raumwaerm_korr_366 = stromverbr_override
    
    # Calculate Daily Values (rows 1-365)
    # These use the reference values calculated above
    daily_rows = WSData.objects.filter(tag_im_jahr__gte=1, tag_im_jahr__lte=365)
    
    for row in daily_rows:
        if (row.verbrauch_promille is not None and row.heizung_abwaerm_promille is not None and
            row.wind_promille is not None and row.solar_promille is not None):
            
            row.stromverbr = stromverbr_raumwaerm_korr_366 * row.verbrauch_promille / 1000
            row.davon_raumw_korr = davon_raumw_korr_366 * row.heizung_abwaerm_promille / 365
            row.stromverbr_raumwaerm_korr = (stromverbr_raumwaerm_korr_366 * row.verbrauch_promille / 1000) + row.davon_raumw_korr
            row.windstrom = row.wind_promille * windstrom_366 / 1000
            row.solarstrom = row.solar_promille * solarstrom_366 / 1000
            row.sonst_kraft_konstant = sonst_kraft_konstant_366 / 365
            row.wind_solar_konstant = row.windstrom + row.solarstrom + row.sonst_kraft_konstant
            
            if row.wind_solar_konstant <= row.stromverbr_raumwaerm_korr:
                row.direktverbr_strom = row.wind_solar_konstant
            else:
                row.direktverbr_strom = row.stromverbr_raumwaerm_korr
            
            if abs(row.direktverbr_strom - row.stromverbr_raumwaerm_korr) < 0.01:
                row.ueberschuss_strom = row.wind_solar_konstant - row.stromverbr_raumwaerm_korr
            else:
                row.ueberschuss_strom = 0
            
            # Calculate Einspeich: =WENN(O/I<=Abregelung;O;I*Abregelung)*EtaStromGas
            # n1 (EtaStromGas) = 0.65, n2 (Abregelung) = 1.0
            if row.stromverbr_raumwaerm_korr > 0:
                ratio = row.ueberschuss_strom / row.stromverbr_raumwaerm_korr
                if ratio <= 1.0:  # Abregelung = 1.0 (100%)
                    row.einspeich = row.ueberschuss_strom * 0.65  # EtaStromGas = 0.65
                else:
                    row.einspeich = row.stromverbr_raumwaerm_korr * 1.0 * 0.65
            else:
                row.einspeich = 0
            
            # Calculate Abregelung.Z column: =WENN(O/I<=Abregelung;0;O-P/EtaStromGas)
            # n1 (EtaStromGas) = 0.65 (from WS diagram)
            # n2 (Abregelung threshold) = 1.0 (from WS diagram - comparison value)
            if row.stromverbr_raumwaerm_korr > 0:
                ratio = row.ueberschuss_strom / row.stromverbr_raumwaerm_korr
                if ratio <= 1.0:  # Within threshold
                    row.abregelung_z = 0  # No curtailment needed
                else:  # Exceeds threshold, calculate curtailment amount
                    row.abregelung_z = row.ueberschuss_strom - (row.einspeich / 0.65)
            else:
                row.abregelung_z = 0
            
            # Calculate Mangel-Last: Stromverbr.Raumw.korr. - Direktverbr. Strom
            row.mangel_last = row.stromverbr_raumwaerm_korr - row.direktverbr_strom
            
            row.save()
    
    # Update Row 366
    # Column H (davon_raumw_korr): From Verbrauch data - NOT a sum
    # Column J (stromverbr_raumwaerm_korr): From WS diagram - NOT a sum
    # All other columns: Sum of rows 1-365
    daily_rows = WSData.objects.filter(tag_im_jahr__gte=1, tag_im_jahr__lte=365)
    sum_stromverbr = sum([r.stromverbr for r in daily_rows if r.stromverbr])
    sum_davon_raumw = sum([r.davon_raumw_korr for r in daily_rows if r.davon_raumw_korr])
    sum_stromverbr_raumwaerm = sum([r.stromverbr_raumwaerm_korr for r in daily_rows if r.stromverbr_raumwaerm_korr])
    sum_windstrom = sum([r.windstrom for r in daily_rows if r.windstrom])
    sum_solarstrom = sum([r.solarstrom for r in daily_rows if r.solarstrom])
    sum_sonst_kraft = sum([r.sonst_kraft_konstant for r in daily_rows if r.sonst_kraft_konstant])
    sum_wind_solar_konstant = sum([r.wind_solar_konstant for r in daily_rows if r.wind_solar_konstant])
    sum_direktverbr = sum([r.direktverbr_strom for r in daily_rows if r.direktverbr_strom])
    sum_ueberschuss = sum([r.ueberschuss_strom for r in daily_rows if r.ueberschuss_strom])
    sum_einspeich = sum([r.einspeich for r in daily_rows if r.einspeich])
    sum_abregelung_z = sum([r.abregelung_z for r in daily_rows if r.abregelung_z])
    sum_mangel_last = sum([r.mangel_last for r in daily_rows if r.mangel_last])
    
    try:
        row_366 = WSData.objects.get(tag_im_jahr=366)
        # Column H: From Verbrauch data - reference value, not sum
        row_366.davon_raumw_korr = davon_raumw_korr_366
        # Column J: From WS diagram - final_stromnetz value
        row_366.stromverbr_raumwaerm_korr = stromverbr_raumwaerm_korr_366
        # All other columns: Sums of rows 1-365
        row_366.stromverbr = sum_stromverbr
        row_366.windstrom = sum_windstrom
        row_366.solarstrom = sum_solarstrom
        row_366.sonst_kraft_konstant = sum_sonst_kraft
        row_366.wind_solar_konstant = sum_wind_solar_konstant
        row_366.direktverbr_strom = sum_direktverbr
        row_366.ueberschuss_strom = sum_ueberschuss
        row_366.einspeich = sum_einspeich
        row_366.abregelung_z = sum_abregelung_z
        row_366.mangel_last = sum_mangel_last
        row_366.save()
    except WSData.DoesNotExist:
        pass
    
    # Update Row 367 (reference row for formulas)
    try:
        row_367 = WSData.objects.get(tag_im_jahr=367)
        # Row 367 Brennstoff-Ausgleichs-Strom = Mangel-Last row 366
        row_367.brennstoff_ausgleichs_strom = sum_mangel_last
        # Row 367 Ladezust.Burtto = 0 (initial value for cumulative calculation)
        if row_367.ladezust_burtto is None:
            row_367.ladezust_burtto = 0
        row_367.save()
    except WSData.DoesNotExist:
        # Create row 367 if it doesn't exist
        row_367 = WSData.objects.create(
            tag_im_jahr=367,
            datum_ref="Sum+1",
            brennstoff_ausgleichs_strom=sum_mangel_last,
            ladezust_burtto=0
        )
    
    # Calculate Brennstoff-Ausgleichs-Strom for daily rows (1-365)
    # Formula: (Bio_S / Brennstoff_367) × MangelLast_current_row
    # Where Brennstoff_367 = MangelLast_366
    if sum_mangel_last > 0:
        sum_brennstoff = 0
        sum_speicher = 0
        sum_ausspeich_rueck = 0
        t1_efficiency = 0.585  # Gas to Power efficiency from WS diagram
        
        # Set row 367 Ladezust.Burtto to 0 as starting point
        try:
            row_367 = WSData.objects.get(tag_im_jahr=367)
            row_367.ladezust_burtto = 0
            row_367.save()
        except WSData.DoesNotExist:
            row_367 = WSData.objects.create(tag_im_jahr=367, datum_ref="Sum+1", ladezust_burtto=0)
        
        # Starting value for cumulative calculation
        ladezust_previous = 0
        
        # First pass: Calculate Ladezust.Burtto for all daily rows (1-365)
        # Formula: Ladezust.Burtto(day) = Ladezust.Burtto(previous) + Einspeich - Ausspeich.Rückverstr. - Ausspeich.Gas
        for row in daily_rows:
            row.brennstoff_ausgleichs_strom = (bio_value / sum_mangel_last) * row.mangel_last
            # Calculate Speicher-Ausgl-Strom: Mangel-Last - Brennstoff-Ausgleichs-Strom
            row.speicher_ausgl_strom = row.mangel_last - row.brennstoff_ausgleichs_strom
            # Calculate Ausspeich.Rückverstr.: Speicher-Ausgl-Strom / t1
            row.ausspeich_rueckverstr = row.speicher_ausgl_strom / t1_efficiency
            # Set Ausspeich. Gas = 0
            row.ausspeich_gas = 0
            # Calculate Ladezust.Burtto cumulatively
            einspeich_val = row.einspeich if row.einspeich is not None else 0
            ausspeich_rueck_val = row.ausspeich_rueckverstr if row.ausspeich_rueckverstr is not None else 0
            ausspeich_gas_val = row.ausspeich_gas if row.ausspeich_gas is not None else 0
            row.ladezust_burtto = ladezust_previous + einspeich_val - ausspeich_rueck_val - ausspeich_gas_val
            row.save()
            
            sum_brennstoff += row.brennstoff_ausgleichs_strom
            sum_speicher += row.speicher_ausgl_strom
            sum_ausspeich_rueck += row.ausspeich_rueckverstr
            ladezust_previous = row.ladezust_burtto  # Update for next iteration
        
        # Row 366: sums of days 1-365
        try:
            row_366 = WSData.objects.get(tag_im_jahr=366)
            row_366.brennstoff_ausgleichs_strom = sum_brennstoff
            row_366.speicher_ausgl_strom = sum_speicher
            row_366.ausspeich_rueckverstr = sum_ausspeich_rueck
            row_366.ausspeich_gas = 0  # Sum of all zeros is 0
            # Ladezust.Burtto row 366: day365 - day1
            try:
                day_365 = WSData.objects.get(tag_im_jahr=365)
                day_1 = WSData.objects.get(tag_im_jahr=1)
                row_366.ladezust_burtto = day_365.ladezust_burtto - day_1.ladezust_burtto
            except WSData.DoesNotExist:
                row_366.ladezust_burtto = None
            row_366.save()
        except WSData.DoesNotExist:
            pass
        
        # Row 367: Set Ladezust.Burtto to minimum of days 1-365
        try:
            row_367 = WSData.objects.get(tag_im_jahr=367)
            daily_ladezust_values = [r.ladezust_burtto for r in daily_rows if r.ladezust_burtto is not None]
            if daily_ladezust_values:
                row_367.ladezust_burtto = min(daily_ladezust_values)
            else:
                row_367.ladezust_burtto = 0
            row_367.save()
        except WSData.DoesNotExist:
            pass
        
        # Second pass: Calculate LADEZUSTAND ABS VORL TL for all daily rows
        # Formula: LADEZUSTAND ABS VORL TL(day) = Ladezust.Burtto(day) - Ladezust.Burtto(row367)
        try:
            row_367 = WSData.objects.get(tag_im_jahr=367)
            ladezust_367 = row_367.ladezust_burtto if row_367.ladezust_burtto is not None else 0
            
            for row in daily_rows:
                if row.ladezust_burtto is not None:
                    row.ladezustand_abs_vorl_tl = row.ladezust_burtto - ladezust_367
                    # Calculate Selbstentl.: LADEZUSTAND ABS VORL TL * 0
                    row.selbstentl = row.ladezustand_abs_vorl_tl * 0
                    row.save()
            
            # Row 366: LADEZUSTAND ABS VORL TL = day365 - day1
            row_366 = WSData.objects.get(tag_im_jahr=366)
            day_365 = WSData.objects.get(tag_im_jahr=365)
            day_1 = WSData.objects.get(tag_im_jahr=1)
            row_366.ladezustand_abs_vorl_tl = day_365.ladezustand_abs_vorl_tl - day_1.ladezustand_abs_vorl_tl
            row_366.selbstentl = row_366.ladezustand_abs_vorl_tl * 0
            row_366.save()
            
            # Third pass: Calculate Ladezustand Netto cumulatively
            # Formula: LadezustandNetto(day) = LadezustandNetto(previous) + Einspeich - Ausspeich.Rückverstr. - Ausspeich.Gas - Selbstentl.
            # Starting value: Row 367 = 0, then calculate cumulatively from day 1
            row_367 = WSData.objects.get(tag_im_jahr=367)
            row_367.ladezustand_netto = 0
            row_367.save()
            ladezustand_netto_previous = 0
            
            for row in daily_rows:
                einspeich_val = row.einspeich if row.einspeich is not None else 0
                ausspeich_rueck = row.ausspeich_rueckverstr if row.ausspeich_rueckverstr is not None else 0
                ausspeich_gas_val = row.ausspeich_gas if row.ausspeich_gas is not None else 0
                selbstentl_val = row.selbstentl if row.selbstentl is not None else 0
                
                row.ladezustand_netto = ladezustand_netto_previous + einspeich_val - ausspeich_rueck - ausspeich_gas_val - selbstentl_val
                row.save()
                ladezustand_netto_previous = row.ladezustand_netto
            
            # Row 366: Ladezustand Netto = day365 - day1
            row_366 = WSData.objects.get(tag_im_jahr=366)
            day_365 = WSData.objects.get(tag_im_jahr=365)
            day_1 = WSData.objects.get(tag_im_jahr=1)
            row_366.ladezustand_netto = day_365.ladezustand_netto - day_1.ladezustand_netto
            row_366.save()
            
            # Row 367: Ladezustand Netto = min of days 1-365
            row_367 = WSData.objects.get(tag_im_jahr=367)
            daily_ladezustand_netto_values = [r.ladezustand_netto for r in daily_rows if r.ladezustand_netto is not None]
            if daily_ladezustand_netto_values:
                row_367.ladezustand_netto = min(daily_ladezustand_netto_values)
            else:
                row_367.ladezustand_netto = 0
            row_367.save()
            
            # Fourth pass: Calculate Ladezustand Abs. for all daily rows
            # Formula: Ladezustand Abs.(day) = Ladezustand Netto(day) - Ladezustand Netto(row367)
            row_367 = WSData.objects.get(tag_im_jahr=367)
            ladezustand_netto_367 = row_367.ladezustand_netto if row_367.ladezustand_netto is not None else 0
            
            for row in daily_rows:
                if row.ladezustand_netto is not None:
                    row.ladezustand_abs = row.ladezustand_netto - ladezustand_netto_367
                    row.save()
            
            # Row 366: Ladezustand Abs. = day365 - day1
            row_366 = WSData.objects.get(tag_im_jahr=366)
            day_365 = WSData.objects.get(tag_im_jahr=365)
            day_1 = WSData.objects.get(tag_im_jahr=1)
            if day_365.ladezustand_abs is not None and day_1.ladezustand_abs is not None:
                row_366.ladezustand_abs = day_365.ladezustand_abs - day_1.ladezustand_abs
            row_366.save()
            
            # Row 367: Ladezustand Abs. = 0 (since it's the reference point)
            row_367.ladezustand_abs = 0
            row_367.save()
        except WSData.DoesNotExist:
            pass


@receiver(post_save, sender=RenewableData)
def renewable_data_changed(sender, instance, **kwargs):
    """Heavy recalculation is manual; only mark stale."""
    print(f"ℹ️ RenewableData {instance.code} changed; full recalculation is manual now.")


@receiver(post_save, sender=VerbrauchData)
def verbrauch_data_changed(sender, instance, **kwargs):
    """Heavy recalculation is manual; only mark stale."""
    print(f"ℹ️ VerbrauchData {instance.code} changed; full recalculation is manual now.")
# Import this in apps.py to register the signals
