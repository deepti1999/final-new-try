from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import json
import pandas as pd
import os
from .models import LandUse, RenewableData, VerbrauchData, CalculationRun
from .calculations import SolarCalculationService, SolarTargetCalculationService
from .recalc_service import run_full_recalc, recalc_all_renewables_full
from simulator.verbrauch_recalculator import recalc_all_verbrauch
from simulator.ws_models import WSData
from simulator.goal_seek import goal_seek
from simulator.signals import compute_ws_diagram_reference, recalculate_ws_data
from calculation_engine.bilanz_engine import calculate_bilanz_data, get_renewable_value

# =============================================================================
# RENEWABLE FORMULA SOURCE: renewable_energy_complete_formulas.py
# VERBRAUCH CALCULATION SOURCE: simulator/verbrauch_calculations.py
# =============================================================================
# All renewable energy formulas (sections 1-9) are centrally managed in:
#   /renewable_energy_complete_formulas.py
#
# The formulas are imported into the Django app via:
#   simulator/renewable_formulas.py (formula registry)
#
# To update formulas:
#   1. Edit renewable_energy_complete_formulas.py
#   2. Run: python manage.py sync_renewable_formulas
#
# The RenewableData model uses get_calculated_values() which reads formulas
# from the database. The formulas in the database are synced from the
# centralized formula file using the management command above.
# =============================================================================

def landing_page(request):
    """Landing page for 100ProSim application"""
    return render(request, 'simulator/landing_page.html')

def user_guide(request):
    """Static quick-start guide with visual pointers to key pages"""
    return render(request, 'simulator/guide.html')

def login_view(request):
    """User login view"""
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, f'Welcome back, {username}!')
                return redirect('simulator:main_simulation')
            else:
                messages.error(request, 'Invalid username or password.')
        else:
            messages.error(request, 'Invalid username or password.')
    else:
        form = AuthenticationForm()
    return render(request, 'simulator/login.html', {'form': form})

def register_view(request):
    """User registration view"""
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            username = form.cleaned_data.get('username')
            messages.success(request, f'Account created for {username}! You can now log in.')
            return redirect('simulator:login')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = UserCreationForm()
    return render(request, 'simulator/register.html', {'form': form})

def logout_view(request):
    """User logout view"""
    logout(request)
    messages.success(request, 'You have been successfully logged out.')
    return redirect('simulator:landing_page')

@login_required
def main_simulation(request):
    """Main simulation dashboard with sidebar navigation"""
    context = {
        'current_section': 'dashboard',
        'total_landuse_records': LandUse.objects.count(),
        'total_renewable_records': RenewableData.objects.count() if hasattr(globals(), 'RenewableData') else 0,
    }
    return render(request, 'simulator/main_simulation.html', context)

def get_landuse_data():
    """Get LandUse data formatted for calculations"""
    data = {}
    landuse_items = LandUse.objects.all()
    
    for landuse in landuse_items:
        if landuse.status_ha is not None:
            data[landuse.code] = float(landuse.status_ha)
    
    # Store original 3.1 value before water mapping overwrites it
    if "3.1" in data:
        data["ORIGINAL_3.1"] = data["3.1"]
    
    # Apply water mapping: 3.1 → 0 (for water calculations)
    if "0" in data and "3.1" in data:
        data["3.1"] = data["0"]  # Water uses total land area
    
    return data

def calculate_percentages(landuse):
    """Calculate percentages and ratios in the web app (not database)"""
    data = {
        'landuse': landuse,
        'status_percent': None,
        'target_percent': None,
        'change_ratio': None,
    }
    
    # Calculate status percentage (child/parent)
    if landuse.parent and landuse.parent.status_ha and landuse.status_ha and landuse.parent.status_ha > 0:
        data['status_percent'] = round((landuse.status_ha / landuse.parent.status_ha) * 100, 1)
    
    # Calculate target percentage (child/parent)
    if landuse.parent and landuse.parent.target_ha and landuse.target_ha and landuse.parent.target_ha > 0:
        data['target_percent'] = round((landuse.target_ha / landuse.parent.target_ha) * 100, 1)
    
    # Calculate change ratio (target/status)
    if landuse.status_ha and landuse.target_ha and landuse.status_ha > 0:
        data['change_ratio'] = round(landuse.target_ha / landuse.status_ha, 2)
    
    return data

@login_required
def landuse_list(request):
    """Display all land use data with calculations done in web app"""
    landuses = LandUse.objects.all().order_by('code')
    latest_run = CalculationRun.objects.first()
    
    # Add calculations for each record (web app layer, not database)
    landuse_data = []
    for landuse in landuses:
        landuse_data.append(calculate_percentages(landuse))
    
    context = {
        'landuse_data': landuse_data,
        'total_count': landuses.count(),
        'current_section': 'landuse',
        'latest_run': latest_run,
    }
    return render(request, 'simulator/landuse_list.html', context)

@login_required
def landuse_detail(request, pk):
    """Display detailed view of a specific land use item"""
    landuse = LandUse.objects.get(pk=pk)
    data = calculate_percentages(landuse)
    
    # Also get children with calculations
    children_data = []
    for child in landuse.children.all():
        children_data.append(calculate_percentages(child))
    
    context = {
        'data': data,
        'children_data': children_data,
    }
    return render(request, 'simulator/landuse_detail.html', context)

def natural_sort_key(code):
    """
    Create a natural sorting key for codes like 1, 2, 3, ... 9, 10, 10.1, etc.
    Converts "10.1.2" to [10, 1, 2] for proper numerical sorting
    """
    import re
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(code))]

@login_required
def renewable_list(request):
    """Display all renewable energy data with hierarchical structure - using dynamic calculations"""
    
    # Get all renewables from database
    renewables = list(RenewableData.objects.all())
    latest_run = CalculationRun.objects.first()
    run_id = request.GET.get("run_id")
    # Sort using natural sorting to get proper order: 1, 2, 3, ... 9, 10, 10.1
    renewables.sort(key=lambda x: natural_sort_key(x.code))
    
    # Build a shared cache for calculations to avoid reloading data 218 times
    # This prevents the memory crash while still enabling dynamic calculations
    calculation_cache = {}
    
    # Pre-load lookup data ONCE for all calculations
    status_lookup = {}
    target_lookup = {}
    
    # Load VerbrauchData once - uses simulator/verbrauch_calculations.py internally
    # get_effective_value() calls calculate_value() from verbrauch_calculations.py
    for verbrauch in VerbrauchData.objects.all():
        effective_status = verbrauch.get_effective_value()
        effective_ziel = verbrauch.get_effective_ziel_value()
        if effective_status is not None:
            status_lookup[verbrauch.code] = float(effective_status)
        if effective_ziel is not None:
            target_lookup[verbrauch.code] = float(effective_ziel)
    
    # Load LandUse data once
    for landuse in LandUse.objects.all():
        if landuse.status_ha is not None:
            status_lookup[str(landuse.code)] = float(landuse.status_ha)
        if landuse.target_ha is not None:
            target_lookup[str(landuse.code)] = float(landuse.target_ha)
    
    # Load RenewableData values once for formula references
    # Only include FIXED values in initial lookup - calculated values will be added dynamically
    for renewable in renewables:
        # Only add fixed values to lookup initially
        if renewable.is_fixed:
            if renewable.status_value is not None:
                status_lookup[renewable.code] = float(renewable.status_value)
            if renewable.target_value is not None:
                target_lookup[renewable.code] = float(renewable.target_value)
    
    # Build hierarchical data structure for template
    hierarchical_data = []
    data_groups = {}
    
    for renewable in renewables:
        # Calculate hierarchy level based on code depth
        code_parts = renewable.code.split('.')
        hierarchy_level = len(code_parts)
        
        # ALWAYS use stored values - they are calculated and updated by backend scripts
        # The get_calculated_values() method is unreliable and returns None for many codes
        display_value = renewable.status_value
        display_target = renewable.target_value

        # Show WS-balanced targets for 9.3.1 and 9.3.4 so the renewable page reflects the latest balance
        if renewable.code in ("9.3.1", "9.3.4") and display_target is not None:
            display_value = display_target
        
        # Add to lookup for any dependencies
        if display_value is not None:
            status_lookup[renewable.code] = float(display_value)
        if display_target is not None:
            target_lookup[renewable.code] = float(display_target)
        
        # Build item for template
        item = {
            'code': renewable.code,
            'name': renewable.name,
            'unit': renewable.unit,
            'hierarchy_level': hierarchy_level,
            'display_value': display_value,
            'display_target': display_target,
            'calculated_value': display_value if renewable.formula else None,
            'is_fixed': renewable.is_fixed,
            'parent_code': '.'.join(code_parts[:-1]) if len(code_parts) > 1 else None,
            'formula': renewable.formula,
            'landuse_source': renewable.landuse_code if hasattr(renewable, 'landuse_code') else None,
            'landuse_code': renewable.landuse_code if hasattr(renewable, 'landuse_code') else None,
        }
        hierarchical_data.append(item)
        
        # Group by category for summary
        category = code_parts[0]
        if category not in data_groups:
            data_groups[category] = []
        data_groups[category].append(renewable)
    
    context = {
        'hierarchical_data': hierarchical_data,
        'data_groups': data_groups,
        'total_count': len(renewables),
        'title': 'Renewable Energy Data - Dynamic Calculations',
        'latest_run': latest_run,
        'run_id': run_id,
    }
    
    return render(request, 'simulator/renewable_list.html', context)

@login_required
def annual_electricity_view(request):
    """Annual electricity section with dynamic renewable data"""
    
    # Prefer TARGET (Ziel) values for the diagram; fall back to status when target is missing/zero
    def get_renewable_status_or_target(code):
        try:
            renewable = RenewableData.objects.get(code=code)
            status_val = renewable.status_value
            target_val = renewable.target_value
            
            if target_val not in (None, 0, 0.0):
                return float(target_val)
            if status_val is not None:
                return float(status_val)
            return 0
        except RenewableData.DoesNotExist:
            return 0
    
    # Backward compatibility helper: target fallback
    def get_renewable_target(code):
        return get_renewable_status_or_target(code)
    
    # ==================================================================================
    # STEP 1: Calculate base renewable values (K, J, L, S, M)
    # ==================================================================================
    # Calculate PV (K) = 1.1.2.1.2 + 1.2.1.2
    pv_value = get_renewable_target('1.1.2.1.2') + get_renewable_target('1.2.1.2')
    
    # Calculate Wind (J) = 2.1.1.2.2 + 2.2.1.2
    wind_value = get_renewable_target('2.1.1.2.2') + get_renewable_target('2.2.1.2')
    
    # Biomass (S) = 4.4.1
    bio_value = get_renewable_target('4.4.1')
    
    # Hydro + Geothermal (L) = 3.1.1.2
    hydro_value = get_renewable_target('3.1.1.2')
    
    # Calculate M total (PV + Wind + Hydro ONLY, Bio is separate)
    m_total = pv_value + wind_value + hydro_value
    
    # ==================================================================================
    # STEP 2: Calculate flows from M
    # ==================================================================================
    # Elektrolyse "nach Angebot" (branch from M) = 9.2.1.5.2
    ely_branch_value = get_renewable_target('9.2.1.5.2')
    
    # Gasspeicher Direktverbr = 9.2.1.5.2 * 65% (hydrogen production efficiency)
    gasspeicher_direkt = ely_branch_value * 0.65
    
    # N value = M - Elektrolyse Power to Gas
    n_value = m_total - ely_branch_value
    
    # ==================================================================================
    # STEP 3: Calculate flows from N (using renewable data as base)
    # ==================================================================================
    # Q (Abregelung) = 9.3.4
    n_input_branch = get_renewable_status_or_target('9.3.4')
    q_abregelung = n_input_branch
    
    # Elektrolyse Stromspeicher (Überschuss) = 9.3.1
    n_output_branch = get_renewable_status_or_target('9.3.1')
    
    # U (Gasspeicher Strom) = Elektrolyse Stromspeicher * 65%
    gas_storage = n_output_branch * 0.65
    
    # T value = U - 160 (storage offset)
    t_value = gas_storage - 160
    
    # T output (Rückverstromung) = T * 58.5% (reconversion efficiency)
    t_output = t_value * 0.585
    
    # O value = N - Q - Elektrolyse Stromspeicher
    n_to_right = n_value - q_abregelung - n_output_branch
    
    # ==================================================================================
    # STEP 4: Override with WS row 366 balanced values if available
    # ==================================================================================
    try:
        ws_row_366 = WSData.objects.get(tag_im_jahr=366)
        
        # If WS row 366 has balanced values, use them
        if ws_row_366.abregelung_z is not None and ws_row_366.abregelung_z > 0:
            q_abregelung = ws_row_366.abregelung_z
            n_input_branch = q_abregelung
        
        if ws_row_366.einspeich is not None and ws_row_366.einspeich > 0:
            # ElektrolyseStromspeicher (Überschuss) = Einspeich / 65%
            n_output_branch = ws_row_366.einspeich / 0.65
            # U (Gasspeicher Strom) = Einspeich (already at 65%)
            gas_storage = ws_row_366.einspeich
            # T value = U - 160
            t_value = gas_storage - 160
        
        if ws_row_366.ausspeich_rueckverstr is not None and ws_row_366.ausspeich_rueckverstr > 0:
            # T output comes from WS daily balance (Ausspeich. Rückverstr. * 58.5%)
            t_output = ws_row_366.ausspeich_rueckverstr * 0.585
        
        # Recalculate O with updated values
        n_to_right = n_value - q_abregelung - n_output_branch
        
    except WSData.DoesNotExist:
        pass
    
    # ==================================================================================
    # STEP 5: Calculate final output
    # ==================================================================================
    # Final Stromnetz zum Endverbrauch = T_output + O + S(Bio)
    final_stromnetz = t_output + n_to_right + bio_value
    
    # Calculate H2 values
    h2_offer = ely_branch_value * 0.65  # H2 from "nach Angebot"
    h2_surplus = n_output_branch * 0.65  # H2 from "Überschuss"
    
    context = {
        'current_section': 'annual_electricity', 
        'title': 'Annual Electricity Analysis',
        # Generation sources
        'bio': round(bio_value, 2),
        'pv': round(pv_value, 2),
        'wind': round(wind_value, 2),
        'hydro': round(hydro_value, 2),
        # M node
        'm_total': round(m_total, 2),
        # Elektrolyse branch from M (9.2.1.5.2)
        'ely_branch_value': round(ely_branch_value, 2),
        'ely_offer': round(ely_branch_value, 2),  # Same as ely_branch_value
        # Gasspeicher Direktverbr
        'gasspeicher_direkt': round(gasspeicher_direkt, 2),
        # N node value
        'n_value': round(n_value, 2),
        # N node branches
        'q_abregelung': round(q_abregelung, 2),
        'n_input_branch': round(n_input_branch, 2),
        'n_output_branch': round(n_output_branch, 2),
        'ely_surplus': round(n_output_branch, 2),  # Elektrolyse Stromspeicher
        # O value (flow to right)
        'n_to_right': round(n_to_right, 2),
        # H2 values
        'h2_offer': round(h2_offer, 2),  # H2 from nach Angebot
        'h2_surplus': round(h2_surplus, 2),  # H2 from Überschuss
        # Storage values
        'gas_storage': round(gas_storage, 2),  # U (Gasspeicher Strom)
        't_value': round(t_value, 2),  # T (before reconversion)
        't_output': round(t_output, 2),  # T output (after 58.5% reconversion)
        # Final output
        'final_stromnetz': round(final_stromnetz, 2),  # Stromnetz zum Endverbrauch
        # Legacy/compatibility values
        'n_input': round(n_input_branch, 2),
        'n_output': round(n_output_branch, 2),
        'h2_to_reconv': round(t_value, 2),
        'reconversion': round(t_output, 2),
        'final_consumption': round(final_stromnetz, 2),
    }
    return render(request, 'simulator/annual_electricity.html', context)


    if "5.1" in data_lookup:  # Windparkfläche → LandUse 5.1 (STORE BEFORE BIOGAS OVERWRITES IT)
        data_lookup["ORIGINAL_5.1"] = data_lookup["5.1"]  # Store original windpark area
        data_lookup["2.1.1"] = data_lookup["5.1"]
    if "0" in data_lookup:  # Laufwasser Bodenfläche → LandUse 0 (Bodenfläche gesamt)
        data_lookup["3.1"] = data_lookup["0"]
    
    # Biogene Brennstoffe LandUse mappings (use original LandUse values before any overwriting)
    # Store original LandUse values under special keys before they get overwritten
    try:
        original_landuse_3_1 = LandUse.objects.get(code="3.1")
        data_lookup["ORIGINAL_3.1"] = float(original_landuse_3_1.status_ha)  # Store original forest area
    except LandUse.DoesNotExist:
        pass
    if "2.2.5" in data_lookup:  # Biogene KUP/Miscanthus → LandUse 2.2.5 (short rotation coppice)
        data_lookup["4.1.2.1"] = data_lookup["2.2.5"]
    if "2.2.1" in data_lookup:  # Getreide-Anbaufläche → LandUse 2.2.1 (grain cultivation)
        data_lookup["4.2.1"] = data_lookup["2.2.1"]
        
    # Biogas LandUse mappings  
    if "2.2.2" in data_lookup:  # Anbaufläche Energiepflanzen für Biogas → LandUse 2.2.2
        data_lookup["5.1"] = data_lookup["2.2.2"]
        
    # Biogene Brennstoffe (flüssig) LandUse mappings
    if "2.2.3" in data_lookup:  # Anbaufläche Ölpflanzen für Biodiesel → LandUse 2.2.3
        data_lookup["6.1.1"] = data_lookup["2.2.3"]
    if "2.2.4" in data_lookup:  # Anbaufläche Energiepflanzen für Bioethanol → LandUse 2.2.4
        data_lookup["6.2.1"] = data_lookup["2.2.4"]
        
    # Same for target data
    if "1.1" in target_data_lookup:
        target_data_lookup["1.1"] = target_data_lookup["1.1"]
    if "2.1" in target_data_lookup:
        target_data_lookup["1.2"] = target_data_lookup["2.1"]
    if "5.1" in target_data_lookup:
        target_data_lookup["ORIGINAL_5.1"] = target_data_lookup["5.1"]  # Store original windpark target
        target_data_lookup["2.1.1"] = target_data_lookup["5.1"]
    if "0" in target_data_lookup:
        target_data_lookup["3.1"] = target_data_lookup["0"]
    
    # Biogene Brennstoffe target mappings (use original LandUse values)
    try:
        original_landuse_3_1_target = LandUse.objects.get(code="3.1")
        target_data_lookup["ORIGINAL_3.1"] = float(original_landuse_3_1_target.target_ha)  # Store original forest target
    except LandUse.DoesNotExist:
        pass
    if "2.2.5" in target_data_lookup:
        target_data_lookup["4.1.2.1"] = target_data_lookup["2.2.5"]
    if "2.2.1" in target_data_lookup:
        target_data_lookup["4.2.1"] = target_data_lookup["2.2.1"]
        
    # Biogas target mappings
    if "2.2.2" in target_data_lookup:  # Anbaufläche Energiepflanzen für Biogas → LandUse 2.2.2
        target_data_lookup["5.1"] = target_data_lookup["2.2.2"]
        
    # Biogene Brennstoffe (flüssig) target mappings
    if "2.2.3" in target_data_lookup:  # Anbaufläche Ölpflanzen für Biodiesel → LandUse 2.2.3
        target_data_lookup["6.1.1"] = target_data_lookup["2.2.3"]
    if "2.2.4" in target_data_lookup:  # Anbaufläche Energiepflanzen für Bioethanol → LandUse 2.2.4
        target_data_lookup["6.2.1"] = target_data_lookup["2.2.4"]
    
    # Then add renewable data (RENEWABLE DATA TAKES PRECEDENCE for renewable calculations)
    for renewable in renewables:
        if renewable.status_value is not None:
            # Always add renewable data - it takes precedence over LandUse for renewable codes
            data_lookup[renewable.code] = float(renewable.status_value)
        if renewable.target_value is not None:
            target_data_lookup[renewable.code] = float(renewable.target_value)
    
    # Group data by category and subcategory, but also add hierarchy info
    data_groups = {}
    hierarchical_data = []
    
    for renewable in renewables:
        category = renewable.category or 'General'
        subcategory = renewable.subcategory or 'Main'
        
        # Calculate hierarchy level from code (number of dots + 1)
        hierarchy_level = len(renewable.code.split('.')) if renewable.code else 1
        
        # Add hierarchy info to the renewable object
        renewable.hierarchy_level = hierarchy_level
        
        # ALWAYS check LandUse data for area codes FIRST (automatic integration)
        landuse_code = None
        if renewable.code == "1.1":  # Solare Dachflächen → LandUse 1.1
            landuse_code = "1.1"
        elif renewable.code.startswith("1.2"):  # Solar Freiflächen chain → LandUse 2.1
            landuse_code = "2.1"
        elif renewable.code == "2.1.1":  # Windparkfläche → LandUse 5.1
            landuse_code = "5.1"
        elif renewable.code == "3.1":  # Laufwasser Bodenfläche → LandUse 0 (Bodenfläche gesamt)
            landuse_code = "0"
        elif renewable.code == "4.1.1.1":  # Biogene Forstfläche → LandUse 3.1
            landuse_code = "3.1"
        elif renewable.code == "4.1.2.1":  # Biogene KUP → LandUse 2.2.5
            landuse_code = "2.2.5"
        elif renewable.code == "4.2.1":  # Getreide-Anbaufläche → LandUse 2.2.1
            landuse_code = "2.2.1"
        elif renewable.code == "5.1":  # Anbaufläche Energiepflanzen für Biogas → LandUse 2.2.2
            landuse_code = "2.2.2"
        elif renewable.code == "6.1.1":  # Anbaufläche Ölpflanzen für Biodiesel → LandUse 2.2.3
            landuse_code = "2.2.3"
        elif renewable.code == "6.2.1":  # Anbaufläche Energiepflanzen für Bioethanol → LandUse 2.2.4
            landuse_code = "2.2.4"
        
        # If this renewable entry should get data from LandUse, use it (PRIORITY)
        if landuse_code and landuse_code in data_lookup:
            # Special case for 4.1.1.1: use original LandUse 3.1 value, not overwritten one
            if renewable.code == "4.1.1.1":
                try:
                    original_landuse_3_1 = LandUse.objects.get(code="3.1")
                    renewable.display_value = float(original_landuse_3_1.status_ha)
                except LandUse.DoesNotExist:
                    renewable.display_value = data_lookup[landuse_code]
            else:
                renewable.display_value = data_lookup[landuse_code]  # ALWAYS use LandUse status
            renewable.landuse_source = True
            renewable.landuse_code = landuse_code
            renewable.calculated_value = None
            
            # ALWAYS use LandUse target if available - FIXED to ensure both status and target work
            if renewable.code == "4.1.1.1":
                # Special case: use original LandUse 3.1 target value
                try:
                    original_landuse_3_1 = LandUse.objects.get(code="3.1")
                    renewable.display_target = float(original_landuse_3_1.target_ha)
                except LandUse.DoesNotExist:
                    renewable.display_target = None
            elif renewable.code == "1.2":
                # Explicit fix for 1.2 → 2.1 connection: ensure both status and target
                try:
                    landuse_2_1 = LandUse.objects.get(code="2.1")
                    renewable.display_value = float(landuse_2_1.status_ha) if landuse_2_1.status_ha else None
                    renewable.display_target = float(landuse_2_1.target_ha) if landuse_2_1.target_ha else None
                    print(f"🔗 FIXED 1.2 → 2.1: Status={renewable.display_value}, Target={renewable.display_target}")
                except LandUse.DoesNotExist:
                    renewable.display_target = None
            elif landuse_code in landuse_targets:
                renewable.display_target = landuse_targets[landuse_code]
            else:
                # Try to calculate target from user_percent if available
                try:
                    landuse_obj = LandUse.objects.get(code=landuse_code)
                    if landuse_obj.user_percent is not None and landuse_obj.parent and landuse_obj.parent.status_ha:
                        # Calculate target from user percentage
                        parent_ha = landuse_obj.parent.status_ha
                        calculated_target = (parent_ha * landuse_obj.user_percent) / 100
                        renewable.display_target = calculated_target
                        print(f"📊 Renewable {renewable.code} target from landuse {landuse_code}: {calculated_target:.2f} ha (user: {landuse_obj.user_percent}%)")
                    else:
                        renewable.display_target = None
                except LandUse.DoesNotExist:
                    renewable.display_target = None
            renewable.calculated_target = None
        elif renewable.is_fixed:
            # PRIORITY: If marked as fixed, use stored values FIRST (even if it has a formula)
            renewable.calculated_value = None
            renewable.calculated_target = None
            renewable.display_value = renewable.status_value
            renewable.display_target = renewable.target_value
            renewable.landuse_source = False
            print(f"📌 FIXED {renewable.code}: Status={renewable.status_value}, Target={renewable.target_value}")
        elif renewable.formula and renewable.formula.startswith("VerbrauchData_"):  # References VerbrauchData
            # Handle VerbrauchData references
            verbrauch_code = renewable.formula.replace('VerbrauchData_', '')
            try:
                verbrauch_data = VerbrauchData.objects.get(code=verbrauch_code)
                renewable.display_value = verbrauch_data.status
                renewable.display_target = verbrauch_data.ziel
                renewable.calculated_value = verbrauch_data.status
                renewable.calculated_target = verbrauch_data.ziel
                renewable.landuse_source = False
                renewable.verbrauch_source = True
                renewable.verbrauch_code = verbrauch_code
                print(f"🔗 VERBRAUCH {renewable.code} → {verbrauch_code}: Status={verbrauch_data.status}, Target={verbrauch_data.ziel}")
            except VerbrauchData.DoesNotExist:
                renewable.display_value = None
                renewable.display_target = None
        elif renewable.formula and renewable.formula.startswith("LandUse_"):  # References LandUse
            # Handle LandUse references
            landuse_code = renewable.formula.replace('LandUse_', '')
            try:
                landuse_data = LandUse.objects.get(code=landuse_code)
                renewable.display_value = landuse_data.status_ha
                renewable.display_target = landuse_data.target_ha
                renewable.calculated_value = landuse_data.status_ha
                renewable.calculated_target = landuse_data.target_ha
                renewable.landuse_source = True
                renewable.verbrauch_source = False
                renewable.landuse_code = landuse_code
                print(f"🔗 LANDUSE {renewable.code} → {landuse_code}: Status={landuse_data.status_ha}, Target={landuse_data.target_ha}")
            except LandUse.DoesNotExist:
                renewable.display_value = None
                renewable.display_target = None
                renewable.calculated_value = None
                renewable.calculated_target = None
                renewable.landuse_source = False
        elif renewable.formula and (
            # Check if it's a RenewableData calculation formula (contains references to other codes)
            any(c.replace('.', '').isdigit() for c in renewable.formula.split()) and
            not renewable.formula.startswith("VerbrauchData_") and
            not renewable.formula.startswith("AUTOMATIC")
        ):
            # Handle RenewableData calculation formulas (e.g., "7.1 * 7.1.1 / 100")
            try:
                calc_status, calc_target = renewable.get_calculated_values()
                renewable.display_value = calc_status
                renewable.display_target = calc_target
                renewable.calculated_value = calc_status
                renewable.calculated_target = calc_target
                renewable.landuse_source = False
                renewable.renewable_calc = True
                print(f"🧮 CALC {renewable.code}: {renewable.formula} = Status:{calc_status}, Target:{calc_target}")
            except Exception as e:
                print(f"❌ Error calculating {renewable.code}: {e}")
                renewable.display_value = None
                renewable.display_target = None
                renewable.calculated_value = None
                renewable.calculated_target = None
                renewable.landuse_source = False
        elif renewable.formula and not (renewable.formula.startswith("AUTOMATIC")):  # Has a calculation formula
            # Create calculation services
            status_calc_service = SolarCalculationService()
            target_calc_service = SolarTargetCalculationService()
            
            # Calculate STATUS value
            calculated_value = status_calc_service.calculate_value(renewable.code, data_lookup)
            renewable.calculated_value = calculated_value
            renewable.display_value = calculated_value
            # Calculate TARGET value using same formula but with target inputs
            calculated_target = target_calc_service.calculate_value(renewable.code, target_data_lookup)
            renewable.calculated_target = calculated_target
            renewable.display_target = calculated_target
            renewable.landuse_source = False
        else:  # Use fixed value from database
            renewable.calculated_value = None
            renewable.calculated_target = None
            renewable.display_value = renewable.status_value
            renewable.display_target = renewable.target_value
            renewable.landuse_source = False
        
        # Get calculation info for display
        calc_service = SolarCalculationService()
        renewable.calc_info = calc_service.get_calculation_info(renewable.code)
        
        hierarchical_data.append(renewable)
        
        if category not in data_groups:
            data_groups[category] = {}
        if subcategory not in data_groups[category]:
            data_groups[category][subcategory] = []
            
        data_groups[category][subcategory].append(renewable)
    
    context = {
        'data_groups': data_groups,
        'hierarchical_data': hierarchical_data,
        'total_count': len(renewables),  # Use len() for Python list instead of .count()
        'calculation_service': SolarCalculationService(),
        'current_section': 'renewable'
    }
    return render(request, 'simulator/renewable_list.html', context)

@login_required 
def cockpit_view(request):
    """
    Cockpit dashboard with dynamic bar charts showing energy balance by sector.
    All data comes from bilanz_engine calculation module.
    """
    # Import the bilanz calculation engine
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from calculation_engine.bilanz_engine import calculate_bilanz_data
    
    try:
        # Get all bilanz data from the calculation engine (fully dynamic)
        bilanz_data = calculate_bilanz_data()
        
        # Helper function to safely get nested values
        def safe_get(data, *keys, default=0):
            """Safely traverse nested dictionary"""
            try:
                result = data
                for key in keys:
                    result = result[key]
                return result if result is not None else default
            except (KeyError, TypeError):
                return default
        
        # Extract and flatten data for template
        context = {
            'current_section': 'cockpit',
            
            # STATUS VALUES (current)
            # Total consumption by sector
            'verbrauch_endenergie_gesamt': safe_get(bilanz_data, 'verbrauch_gesamt', 'status', 'gesamt'),
            'verbrauch_endenergie_klik': safe_get(bilanz_data, 'verbrauch_gesamt', 'status', 'kraft_licht'),
            'verbrauch_endenergie_gebaeudewaerme': safe_get(bilanz_data, 'verbrauch_gesamt', 'status', 'gebaeudewaerme'),
            'verbrauch_endenergie_prozesswaerme': safe_get(bilanz_data, 'verbrauch_gesamt', 'status', 'prozesswaerme'),
            'verbrauch_endenergie_mobile': safe_get(bilanz_data, 'verbrauch_gesamt', 'status', 'mobile'),
            
            # Electricity (Strom)
            'strom_total': safe_get(bilanz_data, 'verbrauch_strom', 'status', 'gesamt'),
            'strom_renewable': safe_get(bilanz_data, 'verbrauch_strom_renewable', 'status', 'gesamt'),
            'strom_fossil': safe_get(bilanz_data, 'verbrauch_strom_fossil', 'status', 'gesamt'),
            
            # Fuels (Brennstoffe)
            'brennstoffe_total': safe_get(bilanz_data, 'verbrauch_fuels', 'status', 'gesamt'),
            'brennstoffe_renewable': safe_get(bilanz_data, 'verbrauch_fuels_renewable', 'status', 'gesamt'),
            'brennstoffe_fossil': safe_get(bilanz_data, 'verbrauch_fuels_fossil', 'status', 'gesamt'),
            
            # Fuel type breakdown
            'brennstoffe_gaseous': safe_get(bilanz_data, 'fuels_breakdown', 'status', 'gaseous'),
            'brennstoffe_liquid': safe_get(bilanz_data, 'fuels_breakdown', 'status', 'liquid'),
            'brennstoffe_solid': safe_get(bilanz_data, 'fuels_breakdown', 'status', 'solid'),
            
            # Heat (Wärme)
            'waerme_total': safe_get(bilanz_data, 'verbrauch_heat', 'status', 'gesamt'),
            'waerme_renewable': safe_get(bilanz_data, 'verbrauch_heat_renewable', 'status', 'gesamt'),
            'waerme_fossil': safe_get(bilanz_data, 'verbrauch_heat_fossil', 'status', 'gesamt'),
            
            # ZIEL VALUES (target)
            # Total consumption by sector
            'verbrauch_endenergie_gesamt_ziel': safe_get(bilanz_data, 'verbrauch_gesamt', 'ziel', 'gesamt'),
            'verbrauch_endenergie_klik_ziel': safe_get(bilanz_data, 'verbrauch_gesamt', 'ziel', 'kraft_licht'),
            'verbrauch_endenergie_gebaeudewaerme_ziel': safe_get(bilanz_data, 'verbrauch_gesamt', 'ziel', 'gebaeudewaerme'),
            'verbrauch_endenergie_prozesswaerme_ziel': safe_get(bilanz_data, 'verbrauch_gesamt', 'ziel', 'prozesswaerme'),
            'verbrauch_endenergie_mobile_ziel': safe_get(bilanz_data, 'verbrauch_gesamt', 'ziel', 'mobile'),
            
            # Electricity (Strom) - Ziel
            'strom_total_ziel': safe_get(bilanz_data, 'verbrauch_strom', 'ziel', 'gesamt'),
            'strom_renewable_ziel': safe_get(bilanz_data, 'verbrauch_strom_renewable', 'ziel', 'gesamt'),
            'strom_fossil_ziel': safe_get(bilanz_data, 'verbrauch_strom_fossil', 'ziel', 'gesamt'),
            
            # Fuels (Brennstoffe) - Ziel
            'brennstoffe_total_ziel': safe_get(bilanz_data, 'verbrauch_fuels', 'ziel', 'gesamt'),
            'brennstoffe_renewable_ziel': safe_get(bilanz_data, 'verbrauch_fuels_renewable', 'ziel', 'gesamt'),
            'brennstoffe_fossil_ziel': safe_get(bilanz_data, 'verbrauch_fuels_fossil', 'ziel', 'gesamt'),
            
            # Fuel type breakdown - Ziel
            'brennstoffe_gaseous_ziel': safe_get(bilanz_data, 'fuels_breakdown', 'ziel', 'gaseous'),
            'brennstoffe_liquid_ziel': safe_get(bilanz_data, 'fuels_breakdown', 'ziel', 'liquid'),
            'brennstoffe_solid_ziel': safe_get(bilanz_data, 'fuels_breakdown', 'ziel', 'solid'),
            
            # Heat (Wärme) - Ziel
            'waerme_total_ziel': safe_get(bilanz_data, 'verbrauch_heat', 'ziel', 'gesamt'),
            'waerme_renewable_ziel': safe_get(bilanz_data, 'verbrauch_heat_renewable', 'ziel', 'gesamt'),
            'waerme_fossil_ziel': safe_get(bilanz_data, 'verbrauch_heat_fossil', 'ziel', 'gesamt'),
        }
        
        return render(request, 'simulator/cockpit.html', context)
        
    except Exception as e:
        # If there's any error, return error page with details
        import traceback
        return render(request, 'simulator/cockpit.html', {
            'current_section': 'cockpit',
            'error': str(e),
            'traceback': traceback.format_exc(),
            # Default zero values for all fields
            'verbrauch_endenergie_gesamt': 0,
            'verbrauch_endenergie_klik': 0,
            'verbrauch_endenergie_gebaeudewaerme': 0,
            'verbrauch_endenergie_prozesswaerme': 0,
            'verbrauch_endenergie_mobile': 0,
            'strom_total': 0,
            'strom_renewable': 0,
            'strom_fossil': 0,
            'brennstoffe_total': 0,
            'brennstoffe_renewable': 0,
            'brennstoffe_fossil': 0,
            'brennstoffe_gaseous': 0,
            'brennstoffe_liquid': 0,
            'brennstoffe_solid': 0,
            'waerme_total': 0,
            'waerme_renewable': 0,
            'waerme_fossil': 0,
            'verbrauch_endenergie_gesamt_ziel': 0,
            'verbrauch_endenergie_klik_ziel': 0,
            'verbrauch_endenergie_gebaeudewaerme_ziel': 0,
            'verbrauch_endenergie_prozesswaerme_ziel': 0,
            'verbrauch_endenergie_mobile_ziel': 0,
            'strom_total_ziel': 0,
            'strom_renewable_ziel': 0,
            'strom_fossil_ziel': 0,
            'brennstoffe_total_ziel': 0,
            'brennstoffe_renewable_ziel': 0,
            'brennstoffe_fossil_ziel': 0,
            'brennstoffe_gaseous_ziel': 0,
            'brennstoffe_liquid_ziel': 0,
            'brennstoffe_solid_ziel': 0,
            'waerme_total_ziel': 0,
            'waerme_renewable_ziel': 0,
            'waerme_fossil_ziel': 0,
        })


def cockpit_view_old(request):
    """OLD VERSION - kept for reference"""
    import json
    
    # Helper function to get values with fallback
    def safe_get_values(obj, is_renewable=False):
        """Get status and target values safely"""
        try:
            if is_renewable:
                status, target = obj.get_calculated_values()
                return (status or 0, target or 0)
            else:
                # Get all energy types
                status_strom = obj.get_effective_strom_value()
                status_gas = obj.get_effective_brennstoffe_gasfoermig_value()
                status_liquid = obj.get_effective_brennstoffe_fluessig_value()
                status_solid = obj.get_effective_brennstoffe_fest_value()
                status_heat = obj.get_effective_waerme_value()
                
                target_strom = obj.get_effective_strom_ziel_value()
                target_gas = obj.get_effective_brennstoffe_gasfoermig_ziel_value()
                target_liquid = obj.get_effective_brennstoffe_fluessig_ziel_value()
                target_solid = obj.get_effective_brennstoffe_fest_ziel_value()
                target_heat = obj.get_effective_waerme_ziel_value()
                
                status_total = status_strom + status_gas + status_liquid + status_solid + status_heat
                target_total = target_strom + target_gas + target_liquid + target_solid + target_heat
                
                return (status_total, target_total)
        except Exception as e:
            print(f"Error in safe_get_values: {e}")
            return (0, 0)
    
    # Get Verbrauch data by category
    categories_data = {
        'status': {},
        'ziel': {}
    }
    
    # KLIK (Kraft/Licht/Kälte)
    try:
        klik = VerbrauchData.objects.get(code='1.4')
        klik_s, klik_t = safe_get_values(klik)
        categories_data['status']['KLIK'] = klik_s
        categories_data['ziel']['KLIK'] = klik_t
    except Exception as e:
        print(f"KLIK error: {e}")
        categories_data['status']['KLIK'] = 0
        categories_data['ziel']['KLIK'] = 0
    
    # Gebäudewärme
    try:
        gw = VerbrauchData.objects.get(code='2.9.0')
        gw_s, gw_t = safe_get_values(gw)
        categories_data['status']['Gebäudewärme'] = gw_s
        categories_data['ziel']['Gebäudewärme'] = gw_t
    except Exception as e:
        print(f"Gebäudewärme error: {e}")
        categories_data['status']['Gebäudewärme'] = 0
        categories_data['ziel']['Gebäudewärme'] = 0
    
    # Prozesswärme
    try:
        pw = VerbrauchData.objects.get(code='3.6.0')
        pw_s, pw_t = safe_get_values(pw)
        categories_data['status']['Prozesswärme'] = pw_s
        categories_data['ziel']['Prozesswärme'] = pw_t
    except Exception as e:
        print(f"Prozesswärme error: {e}")
        categories_data['status']['Prozesswärme'] = 0
        categories_data['ziel']['Prozesswärme'] = 0
    
    # Mobile Anwendungen
    try:
        mobile = VerbrauchData.objects.get(code='4.3.6')
        mobile_s, mobile_t = safe_get_values(mobile)
        categories_data['status']['Mobile'] = mobile_s
        categories_data['ziel']['Mobile'] = mobile_t
    except Exception as e:
        print(f"Mobile error: {e}")
        categories_data['status']['Mobile'] = 0
        categories_data['ziel']['Mobile'] = 0
    
    # Get renewable data
    try:
        renewable = RenewableData.objects.get(code='10')
        ren_s, ren_t = safe_get_values(renewable, is_renewable=True)
        categories_data['status']['Erneuerbar'] = ren_s
        categories_data['ziel']['Erneuerbar'] = ren_t
    except Exception as e:
        print(f"Renewable error: {e}")
        categories_data['status']['Erneuerbar'] = 0
        categories_data['ziel']['Erneuerbar'] = 0
    
    # Calculate totals
    total_verbrauch_status = sum([v for k, v in categories_data['status'].items() if k != 'Erneuerbar'])
    total_verbrauch_ziel = sum([v for k, v in categories_data['ziel'].items() if k != 'Erneuerbar'])
    
    # Add fossil for comparison
    categories_data['status']['Fossil'] = total_verbrauch_status - categories_data['status']['Erneuerbar']
    categories_data['ziel']['Fossil'] = total_verbrauch_ziel - categories_data['ziel']['Erneuerbar']
    
    context = {
        'current_section': 'cockpit',
        'title': 'Energieverbrauch Dashboard',
        'graph_data': categories_data,
        'graph_data_json': json.dumps(categories_data)
    }
    return render(request, 'simulator/cockpit.html', context)

@login_required
@login_required
@require_http_methods(["POST"])
def update_user_percent(request):
    """API endpoint to save user percentage input for land use data"""
    try:
        data = json.loads(request.body)
        code = data.get('code')
        user_percent = data.get('user_percent')
        
        if not code:
            return JsonResponse({'success': False, 'error': 'Code is required'})
            
        # Get the land use record
        landuse = get_object_or_404(LandUse, code=code)
        
        # Update user_percent (allow None/empty for clearing)
        if user_percent == '' or user_percent is None:
            landuse.user_percent = None
        else:
            try:
                landuse.user_percent = float(user_percent)
            except (ValueError, TypeError):
                return JsonResponse({'success': False, 'error': 'Invalid percentage value'})
        
        landuse.save()
        
        return JsonResponse({
            'success': True, 
            'message': f'Saved {code}: {landuse.user_percent}%',
            'code': code,
            'user_percent': landuse.user_percent
        })
        
    except LandUse.DoesNotExist:
        return JsonResponse({'success': False, 'error': f'Land use code {code} not found'})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@require_http_methods(["POST"])
def save_all_user_inputs(request):
    """API endpoint to save all user input values at once"""
    try:
        data = json.loads(request.body)
        user_inputs = data.get('user_inputs', {})
        
        saved_count = 0
        errors = []
        
        for code, percent in user_inputs.items():
            try:
                landuse = LandUse.objects.get(code=code)
                
                if percent == '' or percent is None:
                    landuse.user_percent = None
                else:
                    landuse.user_percent = float(percent)
                
                landuse.save()
                saved_count += 1
                
            except LandUse.DoesNotExist:
                errors.append(f'Code {code} not found')
            except (ValueError, TypeError):
                errors.append(f'Invalid value for {code}: {percent}')
            except Exception as e:
                errors.append(f'Error saving {code}: {str(e)}')
        
        return JsonResponse({
            'success': True,
            'saved_count': saved_count,
            'errors': errors,
            'message': f'Saved {saved_count} values' + (f' with {len(errors)} errors' if errors else '')
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


# PROPER RECURSIVE CASCADE LOGIC - EXACT IMPLEMENTATION
def update_downwards(node, new_percent, total_area):
    """Recursive downward update: parent drives children proportionally"""
    node.user_percent = new_percent
    node.user_ha = total_area * (new_percent / 100)
    node.save()
    
    print(f"📊 Updated {node.code}: {new_percent}% = {node.user_ha:.2f}ha")

    children = node.children.all()
    if not children:
        return

    total_target = sum(child.target_ha for child in children)
    for child in children:
        ratio = child.target_ha / total_target if total_target > 0 else 0
        child_percent = (node.user_ha * ratio / total_area) * 100
        print(f"🔄 Cascading to {child.code}: ratio={ratio:.3f}, new_percent={child_percent:.2f}%")
        update_downwards(child, child_percent, total_area)


def update_upwards(node, total_area):
    """Recursive upward update: children drive parent by summing"""
    parent = node.parent
    if not parent:
        return
    
    parent.user_ha = sum(c.user_ha for c in parent.children.all())
    parent.user_percent = (parent.user_ha / total_area) * 100
    parent.save()
    
    print(f"⬆️ Updated parent {parent.code}: {parent.user_percent:.2f}% = {parent.user_ha:.2f}ha (sum of children)")

    update_upwards(parent, total_area)  # climb upwards


# MASTER UPDATE FUNCTION - EXACT IMPLEMENTATION
def update_node(node, new_percent, total_area):
    """Master function: determines update direction based on node type"""
    if node.children.exists():  # parent node changed
        update_downwards(node, new_percent, total_area)
    else:  # leaf node changed
        node.user_percent = new_percent
        node.user_ha = total_area * (new_percent / 100)
        node.save()
        update_upwards(node, total_area)


@csrf_exempt  
@require_http_methods(["POST"])
def update_user_percent(request, code):
    """API endpoint to update user_percent with proper hierarchical cascading"""
    try:
        node = get_object_or_404(LandUse, code=code)
        new_percent = float(request.POST.get("user_percent", 0))
        
        # Get total area from root node
        root_node = LandUse.objects.get(code="0")
        total_area = root_node.status_ha
        
        print(f"\n{'='*50}")
        print(f"🚀 API CALL: Updating {code} = {new_percent}%")
        print(f"📍 Total area: {total_area:.2f}ha")
        
        # Use master update function
        update_node(node, new_percent, total_area)
        
        # Determine message based on node type
        if node.children.exists():
            message = f"Updated parent {code} and cascaded downwards to {node.children.count()} children"
        else:
            message = f"Updated leaf {code} and cascaded upwards to parents"
            
        print(f"✅ {message}")
        print(f"{'='*50}\n")
        
        return JsonResponse({
            'success': True, 
            'message': message,
            'code': code,
            'user_percent': new_percent
        })
        
    except LandUse.DoesNotExist:
        return JsonResponse({'success': False, 'error': f'LandUse with code {code} not found'})
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Invalid user_percent value'})
    except Exception as e:
        print(f"❌ Error updating {code}: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)})

def verbrauch_view(request):
    """Energy Consumption Data (Verbrauch) - Load from database"""
    from .models import VerbrauchData
    
    # Get all verbrauch data from database
    verbrauch_data = VerbrauchData.objects.all()
    
    # Convert to list of dictionaries with natural sorting
    temp_data = []
    for item in verbrauch_data:
        # Only show calculated values in webapp, not database values
        if item.is_calculated:
            # For calculated items, use separate calculations for status and ziel
            calculated_status = item.calculate_value()  # Uses status fields
            calculated_ziel = item.calculate_ziel_value()  # Uses ziel fields
            display_status = calculated_status
            display_ziel = calculated_ziel
        else:
            # For fixed items, show database values
            display_status = item.status
            display_ziel = item.ziel
        
        # Special case: FC-Traktion alternative entries show "Aktiv" or "(Passiv)" based on user_percent
        if "Alternativ zur" in item.category and "Brennstoffzellen (FC)" in item.category:
            from django.utils.safestring import mark_safe
            if item.user_percent == 100.0:
                display_ziel = mark_safe('<span style="color: blue; font-weight: bold;">Aktiv</span>')
            else:
                display_ziel = mark_safe('<span style="color: green; font-weight: bold;">(Passiv)</span>')
        
        temp_data.append({
            'code': item.code,
            'category': item.category,
            'unit': item.unit,
            'status': display_status,
            'ziel': display_ziel,
            'user_percent': item.user_percent,
            'is_calculated': item.is_calculated,
        })
    
    # Apply natural sorting (same as renewable energy)
    def natural_sort_key(item):
        """Natural sorting for hierarchical codes like 1, 1.1, 1.1.1, 1.2, etc."""
        parts = item['code'].split('.')
        return [int(part) for part in parts]
    
    temp_data.sort(key=natural_sort_key)
    
    # Add section headers after sorting
    data = []
    current_section = None
    
    for item in temp_data:
        # Determine section based on code prefix
        if item['code'].startswith('1'):
            section = 'KLIK'
        elif item['code'].startswith('2'):
            section = 'GW'
        else:
            section = None
        
        # Add section header if we're entering a new section
        if section != current_section and section:
            if section == 'KLIK':
                header_title = 'Kraft, Licht, Information, Kommunikation, Kälte (KLIK)'
            elif section == 'GW':
                header_title = 'Gebäudewärme (GW)'
            
            data.append({
                'is_section_header': True,
                'code': '',
                'category': header_title,
                'unit': '',
                'status': '',
                'ziel': '',
                'user_percent': '',
                'is_calculated': False,
            })
            current_section = section
        
        # For the main KLIK row (code "1"), don't show values as it's just a heading
        if item['code'] == '1':
            item['status'] = ''
            item['ziel'] = ''
            item['unit'] = ''
        
        # Add the actual data row
        item['is_section_header'] = False
        data.append(item)
    
    return render(request, 'simulator/verbrauch.html', {"data": data})


def gebaeudewaerme_view(request):
    """Building Heat Data (Gebäudewärme) - Load from database"""
    from .models import GebaeudewaermeData
    
    # Get all building heat data from database
    gebaeudewaerme_data = GebaeudewaermeData.objects.all()
    
    # Convert to list of dictionaries with natural sorting
    data = []
    for item in gebaeudewaerme_data:
        # For now, just show database values (calculations will be implemented later)
        if item.is_calculated:
            # For calculated items, use separate calculations for status and ziel when implemented
            display_status = item.calculate_value() or None  # Will be None until formulas implemented
            display_ziel = item.calculate_ziel_value() or None  # Will be None until formulas implemented
        else:
            # For fixed items, show database values
            display_status = item.status
            display_ziel = item.ziel
        
        # Special case: FC-Traktion alternative entries show "Aktiv" or "(Passiv)" based on user_percent
        if "Alternativ zur" in item.category and "Brennstoffzellen (FC)" in item.category:
            from django.utils.safestring import mark_safe
            if item.user_percent == 100.0:
                display_ziel = mark_safe('<span style="color: blue; font-weight: bold;">Aktiv</span>')
            else:
                display_ziel = mark_safe('<span style="color: green; font-weight: bold;">(Passiv)</span>')
        
        data.append({
            'code': item.code,
            'category': item.category,
            'unit': item.unit,
            'status': display_status,
            'ziel': display_ziel,
            'formula': item.formula,
            'user_percent': item.user_percent,
            'is_calculated': item.is_calculated,
        })
    
    # Apply natural sorting (same as other modules)
    def natural_sort_key(item):
        """Natural sorting for hierarchical codes like 2.0, 2.1, 2.1.1, 2.2, etc."""
        parts = item['code'].split('.')
        return [int(part) for part in parts]
    
    data.sort(key=natural_sort_key)
    
    return render(request, 'simulator/gebaeudewaerme.html', {"data": data})


def smard_solar_wind(request):
    """SMARD data visualization for solar and wind energy"""
    # 1️⃣ Find your CSV file
    file_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'Actual_generation_202302010000_202401010000_Hour.csv')

    # 2️⃣ Read the CSV (SMARD format)
    df = pd.read_csv(file_path, sep=';', decimal=',')

    # 3️⃣ Clean and select energy sources
    df = df.replace('-', 0)
    
    # Convert German number format to float
    def convert_to_float(value):
        if value == 0 or value == '0':  # Already replaced '-' with 0
            return 0.0
        if isinstance(value, str):
            # German format: 1.721,00 -> English format: 1721.00
            # Remove thousand separators (dots) and replace decimal comma with dot
            value = value.replace('.', '').replace(',', '.')
            return float(value)
        return float(value)
    
    # Convert all energy columns to float
    energy_columns = [
        'Photovoltaics [MWh] Calculated resolutions',
        'Wind onshore [MWh] Calculated resolutions', 
        'Wind offshore [MWh] Calculated resolutions',
        'Hydropower [MWh] Calculated resolutions',
        'Biomass [MWh] Calculated resolutions',
        'Nuclear [MWh] Calculated resolutions',
        'Lignite [MWh] Calculated resolutions',
        'Hard coal [MWh] Calculated resolutions',
        'Fossil gas [MWh] Calculated resolutions'
    ]
    
    for col in energy_columns:
        df[col] = df[col].apply(convert_to_float)

    # Calculate combined values
    df['wind_total_MWh'] = df['Wind onshore [MWh] Calculated resolutions'] + df['Wind offshore [MWh] Calculated resolutions']
    df['total_demand_MWh'] = (df['Photovoltaics [MWh] Calculated resolutions'] + 
                              df['wind_total_MWh'] + 
                              df['Hydropower [MWh] Calculated resolutions'] +
                              df['Biomass [MWh] Calculated resolutions'] +
                              df['Nuclear [MWh] Calculated resolutions'] +
                              df['Lignite [MWh] Calculated resolutions'] +
                              df['Hard coal [MWh] Calculated resolutions'] +
                              df['Fossil gas [MWh] Calculated resolutions'])

    # 4️⃣ Group by day and sum hourly values to get daily totals (MWh/day)
    df['Date'] = pd.to_datetime(df['Start date'])
    df['day'] = df['Date'].dt.date
    
    daily = df.groupby('day').agg({
        'Photovoltaics [MWh] Calculated resolutions': 'sum',
        'wind_total_MWh': 'sum',
        'Hydropower [MWh] Calculated resolutions': 'sum',
        'Biomass [MWh] Calculated resolutions': 'sum',
        'total_demand_MWh': 'sum'
    }).reset_index()

    # 5️⃣ Rename columns with proper units and SMARD designation
    daily = daily.rename(columns={
        'day': 'date',
        'Photovoltaics [MWh] Calculated resolutions': 'solar_smard_MWh',
        'wind_total_MWh': 'wind_smard_MWh',
        'Hydropower [MWh] Calculated resolutions': 'hydro_MWh',
        'Biomass [MWh] Calculated resolutions': 'bio_MWh',
        'total_demand_MWh': 'demand_MWh'
    })
    
    # PART A — Build the scenario generation curve from SMARD + totals
    # 1) Data is already aggregated to daily
    
    # 2) Create the shape (normalize) - per-unit curves
    # Using sum (not max) to keep energy-weighted shape
    solar_total = daily['solar_smard_MWh'].sum()
    wind_total = daily['wind_smard_MWh'].sum()
    hydro_total = daily['hydro_MWh'].sum()
    bio_total = daily['bio_MWh'].sum()
    demand_total = daily['demand_MWh'].sum()
    
    # Create normalized per-unit curves
    daily['solar_pu'] = daily['solar_smard_MWh'] / solar_total if solar_total > 0 else 0
    daily['wind_pu'] = daily['wind_smard_MWh'] / wind_total if wind_total > 0 else 0
    daily['hydro_pu'] = daily['hydro_MWh'] / hydro_total if hydro_total > 0 else 0
    daily['bio_pu'] = daily['bio_MWh'] / bio_total if bio_total > 0 else 0
    daily['demand_pu'] = daily['demand_MWh'] / demand_total if demand_total > 0 else 0
    
    # Add totals for reference
    daily['solar_total_GWh'] = solar_total / 1000  # Convert to GWh
    daily['wind_total_GWh'] = wind_total / 1000
    daily['hydro_total_GWh'] = hydro_total / 1000
    daily['bio_total_GWh'] = bio_total / 1000
    daily['demand_total_GWh'] = demand_total / 1000
    
    # 3) Scale each shape to scenario annual totals (from Renewable data)
    # Get target values from your Renewable data model
    try:
        from .models import RenewableData
        
        # Get scenario targets - looking for specific renewable codes
        pv_target_record = RenewableData.objects.filter(code__icontains='solar').first() or \
                          RenewableData.objects.filter(code__icontains='photovoltaic').first() or \
                          RenewableData.objects.filter(code__icontains='pv').first()
        
        wind_target_record = RenewableData.objects.filter(code__icontains='wind').first()
        
        hydro_target_record = RenewableData.objects.filter(code__icontains='hydro').first() or \
                             RenewableData.objects.filter(code__icontains='water').first()
        
        bio_target_record = RenewableData.objects.filter(code__icontains='bio').first() or \
                           RenewableData.objects.filter(code__icontains='biomass').first()
        
        # Extract target values (assuming they're in GWh/a)
        PV_target_GWh = float(pv_target_record.ziel or pv_target_record.status or 0) if pv_target_record else 50.0  # Default fallback
        Wind_target_GWh = float(wind_target_record.ziel or wind_target_record.status or 0) if wind_target_record else 200.0  # Default fallback  
        Hydro_target_GWh = float(hydro_target_record.ziel or hydro_target_record.status or 0) if hydro_target_record else 25.0  # Default fallback
        Bio_target_GWh = float(bio_target_record.ziel or bio_target_record.status or 0) if bio_target_record else 30.0  # Default fallback
        
    except Exception as e:
        # Fallback values if RenewableData is not available or has issues
        print(f"Using fallback renewable targets: {e}")
        PV_target_GWh = 50.0     # Example target
        Wind_target_GWh = 200.0  # Example target
        Hydro_target_GWh = 25.0  # Example target
        Bio_target_GWh = 30.0    # Example target
    
    # Convert annual targets from GWh/a to MWh/a
    PV_target_MWh = PV_target_GWh * 1000
    Wind_target_MWh = Wind_target_GWh * 1000  
    Hydro_target_MWh = Hydro_target_GWh * 1000
    Bio_target_MWh = Bio_target_GWh * 1000
    
    # Distribute targets over the year using the normalized shapes
    daily['solar_scenario_MWh_day'] = daily['solar_pu'] * PV_target_MWh
    daily['wind_scenario_MWh_day'] = daily['wind_pu'] * Wind_target_MWh
    daily['hydro_scenario_MWh_day'] = Hydro_target_MWh / 365  # Constant daily
    daily['bio_scenario_MWh_day'] = daily['bio_pu'] * Bio_target_MWh  # Follow historical pattern
    
    # 4) Sum to total renewable scenario (per day)
    daily['ren_total_MWh_day'] = (daily['solar_scenario_MWh_day'] + 
                                  daily['wind_scenario_MWh_day'] + 
                                  daily['hydro_scenario_MWh_day'] + 
                                  daily['bio_scenario_MWh_day'])
    
    # Quick check: sum(ren_total_MWh_day) ≈ (PV + Wind + Hydro + Bio) targets (in MWh)
    calculated_total_MWh = daily['ren_total_MWh_day'].sum()
    expected_total_MWh = PV_target_MWh + Wind_target_MWh + Hydro_target_MWh + Bio_target_MWh
    daily['calculated_total_GWh'] = calculated_total_MWh / 1000
    daily['expected_total_GWh'] = expected_total_MWh / 1000
    daily['total_check_diff_percent'] = ((calculated_total_MWh - expected_total_MWh) / expected_total_MWh * 100) if expected_total_MWh > 0 else 0
    
    # Add scenario targets for reference
    daily['PV_target_GWh'] = PV_target_GWh
    daily['Wind_target_GWh'] = Wind_target_GWh
    daily['Hydro_target_GWh'] = Hydro_target_GWh
    daily['Bio_target_GWh'] = Bio_target_GWh
    
    # PART B — Create WS.2a "segmentiert" curve (Excel's trick)
    # 5) Make the segmentiert ordering
    # Excel WS.2a sorts days by renewable total (highest → lowest)
    # Create two equally sorted arrays: both sorted descending
    
    # Sort renewable generation by descending order (highest first)
    ren_sorted = daily['ren_total_MWh_day'].sort_values(ascending=False).reset_index(drop=True)
    
    # Use YOUR ACTUAL DEMAND from VerbrauchData instead of SMARD historical demand
    # Get total electricity consumption from VerbrauchData (Code 5)
    try:
        from .models import VerbrauchData
        electricity_total_entry = VerbrauchData.objects.filter(code='5').first()  # Total electricity consumption
        
        if electricity_total_entry:
            # Uses simulator/verbrauch_calculations.py for all calculations
            if electricity_total_entry.is_calculated:
                verbrauch_status_GWh = electricity_total_entry.calculate_value()
                verbrauch_ziel_GWh = electricity_total_entry.calculate_ziel_value()
            else:
                verbrauch_status_GWh = electricity_total_entry.status
                verbrauch_ziel_GWh = electricity_total_entry.ziel
            
            # Convert to MWh/a
            verbrauch_status_MWh_per_year = verbrauch_status_GWh * 1000
            verbrauch_ziel_MWh_per_year = verbrauch_ziel_GWh * 1000
            
            print(f"🔌 Using YOUR VERBRAUCH DATA for demand:")
            print(f"   Status: {verbrauch_status_GWh:.0f} GWh/a = {verbrauch_status_MWh_per_year:.0f} MWh/a")
            print(f"   Ziel: {verbrauch_ziel_GWh:.0f} GWh/a = {verbrauch_ziel_MWh_per_year:.0f} MWh/a")
            
            # Use STATUS demand for current analysis (you can switch to ZIEL if needed)
            annual_demand_MWh = verbrauch_status_MWh_per_year
            daily_average_demand_MWh = annual_demand_MWh / 365
            
        else:
            print("⚠️ Could not find VerbrauchData Code 5, using fallback")
            annual_demand_MWh = 400000 * 1000  # 400 GWh/a fallback
            daily_average_demand_MWh = annual_demand_MWh / 365
            
    except Exception as e:
        print(f"⚠️ Error getting VerbrauchData: {e}, using fallback")
        annual_demand_MWh = 400000 * 1000  # 400 GWh/a fallback  
        daily_average_demand_MWh = annual_demand_MWh / 365
    
    # Create demand curve using the historical SMARD demand SHAPE but scaled to YOUR total
    # This gives us a realistic daily variation pattern scaled to your actual consumption
    if daily['demand_MWh'].sum() > 0:
        # Use SMARD shape but scale to your total demand
        smard_demand_shape = daily['demand_MWh'] / daily['demand_MWh'].sum()  # Normalize SMARD shape
        daily['verbrauch_demand_MWh'] = smard_demand_shape * annual_demand_MWh  # Scale to your annual total
    else:
        # Fallback to constant daily demand if no SMARD data
        daily['verbrauch_demand_MWh'] = daily_average_demand_MWh
    
    # Sort YOUR ACTUAL DEMAND by descending order (highest first) - independent of renewables
    dmd_sorted = daily['verbrauch_demand_MWh'].sort_values(ascending=False).reset_index(drop=True)
    
    # Add VerbrauchData totals for reference
    daily['verbrauch_status_GWh'] = verbrauch_status_GWh if 'verbrauch_status_GWh' in locals() else 0
    daily['verbrauch_ziel_GWh'] = verbrauch_ziel_GWh if 'verbrauch_ziel_GWh' in locals() else 0
    daily['annual_demand_check_GWh'] = annual_demand_MWh / 1000 if 'annual_demand_MWh' in locals() else 0
    
    # Create segmentiert dataset (chronology removed, sorted pairs)
    segmentiert_data = pd.DataFrame({
        'day_rank': range(1, len(ren_sorted) + 1),  # 1 to 365 (or number of days)
        'ren_sorted_MWh': ren_sorted,
        'dmd_sorted_MWh': dmd_sorted
    })
    
    # PART C — Compute surplus/deficit & storage flows
    # 6) Daily surplus in the segmentiert space
    surplus_sorted = ren_sorted - dmd_sorted
    
    # 7) Stromaufnahme (Überschussphasen) — Sum only the positive parts
    surplus_positive = surplus_sorted[surplus_sorted > 0]  # Filter only positive surplus
    stromaufnahme_MWh = surplus_positive.sum()  # Sum positive surplus in MWh
    stromaufnahme_GWh = stromaufnahme_MWh / 1000  # Convert to GWh
    
    print(f"📊 STROMAUFNAHME CALCULATION:")
    print(f"   Positive surplus days: {len(surplus_positive)} out of {len(surplus_sorted)} days")
    print(f"   Total surplus energy: {stromaufnahme_MWh:.0f} MWh = {stromaufnahme_GWh:.1f} GWh")
    print(f"🔋 FINAL STROMAUFNAHME VALUE: {stromaufnahme_GWh:.1f} GWh/a")
    
    # Add segmentiert data to daily for template access
    daily['day_rank'] = range(1, len(daily) + 1)
    daily['ren_sorted_MWh'] = ren_sorted
    daily['dmd_sorted_MWh'] = dmd_sorted  # This now uses YOUR VerbrauchData
    daily['surplus_sorted_MWh'] = surplus_sorted
    
    # Add Stromaufnahme values for template access
    daily['stromaufnahme_MWh'] = stromaufnahme_MWh
    daily['stromaufnahme_GWh'] = stromaufnahme_GWh
    daily['surplus_days_count'] = len(surplus_positive)
    daily['total_days_count'] = len(surplus_sorted)
    daily['surplus_days_percent'] = (len(surplus_positive) / len(surplus_sorted) * 100) if len(surplus_sorted) > 0 else 0
    
    # Quick verification: total demand should match your VerbrauchData
    total_demand_check_MWh = daily['verbrauch_demand_MWh'].sum()
    daily['demand_verification_GWh'] = total_demand_check_MWh / 1000
    daily['demand_difference_percent'] = ((total_demand_check_MWh - annual_demand_MWh) / annual_demand_MWh * 100) if 'annual_demand_MWh' in locals() else 0

    # 6️⃣ Send data to the web page
    data = daily.to_dict(orient='records')
    
    # Convert datetime objects to strings for JavaScript
    for record in data:
        if 'date' in record:
            record['date'] = record['date'].strftime('%Y-%m-%d')

    return render(request, 'simulator/smard_solar_wind.html', {'data': data})


@login_required
def bilanz_view(request):
    """
    Bilanz (Balance Sheet) View
    Compares supply (Aktiva: Renewable + Fossil) with demand (Passiva: Verbrauch)
    Structure: Erneuerbar + Fossil (Aktiva) = Verbrauch (Passiva)
    
    All calculations are dynamically pulled from RenewableData and VerbrauchData
    using the bilanz_engine calculation module.
    """
    
    # Import the bilanz calculation engine
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from calculation_engine.bilanz_engine import calculate_bilanz_data
    
    # Get all bilanz data from the calculation engine (fully dynamic)
    bilanz_data = calculate_bilanz_data()
    bilanz_data['latest_run'] = CalculationRun.objects.first()
    
    # Add current section to context
    bilanz_data['current_section'] = 'bilanz'
    
    return render(request, 'simulator/bilanz.html', bilanz_data)

# ============================
# NEW LANDUSE AJAX UPDATE VIEW
# ============================

@csrf_exempt
@login_required
def update_landuse_percent(request, pk):
    """
    Update the user_percent of a LandUse item and recalc target_ha automatically.
    """
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST method required"}, status=400)

    try:
        data = json.loads(request.body)
        new_percent = float(data.get("user_percent"))
        
        # Validate percentage range
        if new_percent < 0 or new_percent > 100:
            return JsonResponse({
                "status": "error", 
                "message": "Percentage must be between 0 and 100"
            }, status=400)
            
    except (ValueError, TypeError) as e:
        return JsonResponse({
            "status": "error", 
            "message": "Invalid percentage value"
        }, status=400)
    except Exception as e:
        return JsonResponse({
            "status": "error", 
            "message": "Invalid request data"
        }, status=400)

    try:
        landuse = get_object_or_404(LandUse, pk=pk)
        
        if not landuse.parent:
            return JsonResponse({
                "status": "error",
                "message": "Cannot update root level land use"
            }, status=400)
        
        landuse.user_percent = new_percent

        # LandUse.save() already recalculates target_ha
        landuse.save(force_recalc=True)

        # Calculate target percent
        target_percent = (landuse.target_ha / landuse.parent.target_ha * 100) if landuse.parent and landuse.parent.target_ha else 0

        # Send updated values back to page
        return JsonResponse({
            "status": "ok",
            "new_target_ha": float(landuse.target_ha) if landuse.target_ha else 0,
            "new_target_percent": float(target_percent),
            "message": f"Updated {landuse.code} to {new_percent}%"
        })
        
    except Exception as e:
        return JsonResponse({
            "status": "error",
            "message": f"Failed to update: {str(e)}"
        }, status=500)


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def balance_ws_storage(request):
    """
    GoalSeek Stromverbr. Raumw.korr. (row 366) until LadezustandNetto (row 366) == 0.
    Uses secant method, matching Excel GoalSeek behavior.
    """
    diagram = compute_ws_diagram_reference()
    reference_stromverbr = diagram.get("stromverbr_raumwaerm_korr_366", 0) or 0

    # First pass: use the diagram reference exactly once (seed state)
    recalculate_ws_data(stromverbr_override=reference_stromverbr, use_diagram_reference=True)

    def storage_balance(stromverbr_value: float) -> float:
        # Override with proposed value; do not recompute from diagram inside the loop
        recalculate_ws_data(stromverbr_override=stromverbr_value, use_diagram_reference=False)
        try:
            row_366 = WSData.objects.get(tag_im_jahr=366)
            return row_366.ladezustand_netto or 0.0
        except WSData.DoesNotExist:
            return 0.0

    # Set initial guesses for secant: current value and a small nudge
    x0 = reference_stromverbr
    x1 = reference_stromverbr * 1.05 if reference_stromverbr != 0 else 1.0

    final_value = goal_seek(storage_balance, x0, x1, target=0.0, tol=1e-6, max_iter=30)

    # One final pass to persist the converged value
    recalculate_ws_data(stromverbr_override=final_value, use_diagram_reference=False)
    row_366 = WSData.objects.get(tag_im_jahr=366)

    # Derived values for the Annual Electricity diagram after balancing:
    # Q (Abregelung) comes from WS row 366 Abregelung.Z
    abregelung_ws = row_366.abregelung_z or 0.0
    # N ElektrolyseStromspeicher (Überschuss) comes from EINSPEICH / n1 (0.65)
    n1_eff = 0.65
    # Requested logic: ElektrolyseStromspeicher (Überschuss) = Einspeich / n1
    ely_surplus_ws = (row_366.einspeich or 0.0) / n1_eff if n1_eff else 0.0
    h2_surplus_ws = ely_surplus_ws * n1_eff

    # U (Gasspeicher Strom) stays tied to Einspeich path (Hydrogen created)
    gas_storage_ws = h2_surplus_ws
    # T uses Ausspeich. Rückverstr. if present; U remains from Einspeich
    if row_366.ausspeich_rueckverstr is not None:
        t_value_ws = row_366.ausspeich_rueckverstr * 0.585
    else:
        t_value_ws = gas_storage_ws * 0.585

    # Push balanced WS values back into RenewableData (target only; keep status untouched)
    try:
        RenewableData.objects.filter(code='9.3.4').update(target_value=abregelung_ws)
    except RenewableData.DoesNotExist:
        pass

    try:
        RenewableData.objects.filter(code='9.3.1').update(target_value=ely_surplus_ws)
    except RenewableData.DoesNotExist:
        pass

    # Recalculate dependents so downstream targets (e.g., 10.x) reflect updated 9.3.1/9.3.4
    recalc_all_renewables_full()

    return JsonResponse({
        "status": "ok",
        "reference_stromverbr": reference_stromverbr,
        "final_stromverbr": final_value,
        "ladezustand_netto_row_366": row_366.ladezustand_netto,
        "abregelung_ws": abregelung_ws,
        "ely_surplus_ws": ely_surplus_ws,
        "h2_surplus_ws": h2_surplus_ws,
        "gas_storage_ws": gas_storage_ws,
        "t_value_ws": t_value_ws,
    })


@login_required
@require_http_methods(["POST"])
def balance_energy(request):
    """
    GoalSeek outer loop: adjust Solar (LU_2.1) or Wind (LU_1.1) land area until
    renewable_by_sector.ziel.gesamt matches verbrauch_gesamt.ziel.gesamt (gap ≈ 0).
    """
    try:
        data = json.loads(request.body or "{}")
    except Exception:
        data = {}

    driver = data.get("driver", "solar")
    tolerance = float(data.get("tolerance", 1.0))  # GWh tolerance for total gap

    driver_code = "LU_2.1" if driver == "solar" else "LU_1.1"
    try:
        lu = LandUse.objects.get(code=driver_code)
    except LandUse.DoesNotExist:
        return JsonResponse({"status": "error", "message": f"LandUse {driver_code} not found. Available: LU_1.1 (wind), LU_2.1 (solar)"}, status=400)

    def set_and_gap(target_ha: float):
        lu.target_ha = max(0, target_ha)
        lu.target_locked = True
        lu.save(skip_cascade=False, force_recalc=False)
        lu.refresh_from_db()
        recalc_all_renewables_full()
        bilanz = calculate_bilanz_data()
        demand = bilanz.get("verbrauch_gesamt", {}).get("ziel", {}).get("gesamt", 0) or 0
        renewable = bilanz.get("renewable_by_sector", {}).get("ziel", {}).get("gesamt", 0) or 0
        gap = demand - renewable  # positive gap => need more renewable
        return gap, demand, renewable, lu.target_ha

    base_ha = lu.target_ha or 0
    gap0, demand0, renewable0, ha0 = set_and_gap(base_ha)

    if abs(gap0) <= tolerance:
        return JsonResponse({"status": "ok", "summary": {"status": "balanced", "final_gap": gap0, "final_ha": ha0, "iterations": 0}})

    # Choose second guess direction based on gap sign
    if gap0 > 0:
        x1 = ha0 * 1.1 + 100 if ha0 == 0 else ha0 * 1.1
    else:
        x1 = max(ha0 * 0.9, 0)

    def gap_func(area):
        g, _, _, _ = set_and_gap(area)
        return g

    final_ha = goal_seek(gap_func, ha0, x1, target=0.0, tol=tolerance, max_iter=30)
    final_gap, final_demand, final_renewable, final_ha = set_and_gap(final_ha)

    summary = {
        "status": "balanced" if abs(final_gap) <= tolerance else "partial",
        "initial_gap": gap0,
        "final_gap": final_gap,
        "initial_ha": ha0,
        "final_ha": final_ha,
        "demand": final_demand,
        "renewable": final_renewable,
        "driver": driver_code,
    }
    return JsonResponse({"status": "ok", "summary": summary})


@login_required
@require_http_methods(["POST"])
def run_full_recalc_view(request):
    """
    Explicitly run the heavy cascade once and store a CalculationRun snapshot.
    Intended for the staged “calculate once, read many” flow.
    """
    summary = run_full_recalc()
    run = CalculationRun.objects.create(
        duration_ms=summary["duration_ms"],
        summary=summary,
        triggered_by=request.user.username,
    )
    request.session["latest_run_id"] = run.id
    return JsonResponse(
        {
            "status": "ok",
            "run_id": run.id,
            "duration_ms": run.duration_ms,
            "summary": summary,
            "created_at": run.created_at.isoformat(),
        }
    )
