"""
Renewable Energy Formula Registry
==================================

This module provides centralized formula management for renewable energy calculations.
It imports formulas from renewable_energy_complete_formulas.py and integrates them
with Django models and views.

This is the SINGLE SOURCE OF TRUTH for all renewable energy formulas (sections 1-9).
"""

import sys
import os

# Add parent directory to path to import the complete formulas file
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import all formula dictionaries from the complete formulas file
try:
    from renewable_energy_complete_formulas import (
        SECTION_1_FORMULAS,
        SECTION_2_FORMULAS,
        SECTION_3_FORMULAS,
        SECTION_4_FORMULAS,
        SECTION_5_FORMULAS,
        SECTION_6_FORMULAS,
        SECTION_7_FORMULAS,
        SECTION_8_FORMULAS,
        SECTION_9_FORMULAS,
    )
except ImportError:
    # Silently use fallback - formulas are already in renewable_formulas.py
    # Define empty dictionaries as fallback
    SECTION_1_FORMULAS = {}
    SECTION_2_FORMULAS = {}
    SECTION_3_FORMULAS = {}
    SECTION_4_FORMULAS = {}
    SECTION_5_FORMULAS = {}
    SECTION_6_FORMULAS = {}
    SECTION_7_FORMULAS = {}
    SECTION_8_FORMULAS = {}
    SECTION_9_FORMULAS = {}


# Combine all formulas into a single registry
ALL_RENEWABLE_FORMULAS = {
    **SECTION_1_FORMULAS,
    **SECTION_2_FORMULAS,
    **SECTION_3_FORMULAS,
    **SECTION_4_FORMULAS,
    **SECTION_5_FORMULAS,
    **SECTION_6_FORMULAS,
    **SECTION_7_FORMULAS,
    **SECTION_8_FORMULAS,
    **SECTION_9_FORMULAS,
}


def get_formula_for_code(code):
    """
    Get the formula definition for a specific renewable energy code.
    
    Args:
        code (str): Renewable energy code (e.g., '1.1.2.1.2')
    
    Returns:
        dict: Formula definition with keys: name, formula, is_fixed, description
        None: If code not found
    """
    return ALL_RENEWABLE_FORMULAS.get(code)


def get_formula_string(code):
    """
    Get just the formula string for a code.
    
    Args:
        code (str): Renewable energy code
    
    Returns:
        str: Formula string or None
    """
    formula_def = get_formula_for_code(code)
    if formula_def:
        return formula_def.get('formula')
    return None


def is_code_calculated(code):
    """
    Check if a code should be calculated (not fixed).
    
    Args:
        code (str): Renewable energy code
    
    Returns:
        bool: True if code should be calculated, False if fixed
    """
    formula_def = get_formula_for_code(code)
    if formula_def:
        return not formula_def.get('is_fixed', True)
    return False


def get_all_formula_codes():
    """
    Get all renewable energy codes that have formulas.
    
    Returns:
        list: List of all codes with formulas
    """
    return list(ALL_RENEWABLE_FORMULAS.keys())


def get_formulas_by_section(section):
    """
    Get all formulas for a specific section.
    
    Args:
        section (int): Section number (1-9)
    
    Returns:
        dict: All formulas for that section
    """
    section_map = {
        1: SECTION_1_FORMULAS,
        2: SECTION_2_FORMULAS,
        3: SECTION_3_FORMULAS,
        4: SECTION_4_FORMULAS,
        5: SECTION_5_FORMULAS,
        6: SECTION_6_FORMULAS,
        7: SECTION_7_FORMULAS,
        8: SECTION_8_FORMULAS,
        9: SECTION_9_FORMULAS,
    }
    return section_map.get(section, {})


def sync_formulas_to_database():
    """
    Sync all formulas from the formula registry to the database.
    Updates formula and is_fixed fields in RenewableData model.
    
    This should be called after any formula updates to ensure database is in sync.
    
    Returns:
        dict: Statistics about the sync operation
    """
    from .models import RenewableData
    
    stats = {
        'updated': 0,
        'created': 0,
        'skipped': 0,
        'errors': []
    }
    
    for code, formula_def in ALL_RENEWABLE_FORMULAS.items():
        try:
            # Try to get existing entry
            renewable = RenewableData.objects.filter(code=code).first()
            
            if renewable:
                # Update existing entry
                changed = False
                
                if renewable.formula != formula_def.get('formula'):
                    renewable.formula = formula_def.get('formula')
                    changed = True
                
                if renewable.is_fixed != formula_def.get('is_fixed', True):
                    renewable.is_fixed = formula_def.get('is_fixed', True)
                    changed = True
                
                if changed:
                    renewable.save()
                    stats['updated'] += 1
                else:
                    stats['skipped'] += 1
            else:
                # Entry doesn't exist - log it but don't create
                # (We don't create because we need other data like name, units, etc.)
                stats['errors'].append(f"Code {code} not found in database")
                
        except Exception as e:
            stats['errors'].append(f"Error syncing {code}: {str(e)}")
    
    return stats


def validate_formula_coverage():
    """
    Validate that all formulas in the registry exist in the database.
    
    Returns:
        dict: Validation results with missing codes and extra codes
    """
    from .models import RenewableData
    
    # Get all codes from registry
    registry_codes = set(ALL_RENEWABLE_FORMULAS.keys())
    
    # Get all codes from database (sections 1-9 only)
    db_codes = set(
        RenewableData.objects.filter(
            code__regex=r'^[1-9]\.'
        ).exclude(
            code__startswith='10.'
        ).values_list('code', flat=True)
    )
    
    results = {
        'total_registry': len(registry_codes),
        'total_database': len(db_codes),
        'missing_in_db': list(registry_codes - db_codes),
        'missing_in_registry': list(db_codes - registry_codes),
        'in_sync': registry_codes == db_codes
    }
    
    return results


def get_formula_description(code):
    """
    Get the description for a formula.
    
    Args:
        code (str): Renewable energy code
    
    Returns:
        str: Description or None
    """
    formula_def = get_formula_for_code(code)
    if formula_def:
        return formula_def.get('description')
    return None


# =============================================================================
# FORMULA EVALUATION HELPERS
# =============================================================================

def parse_formula_dependencies(formula):
    """
    Parse a formula and extract all code dependencies.
    
    Args:
        formula (str): Formula string
    
    Returns:
        dict: Dependencies by type (renewable_codes, landuse_codes, verbrauch_codes)
    """
    import re
    
    if not formula:
        return {'renewable_codes': [], 'landuse_codes': [], 'verbrauch_codes': []}
    
    dependencies = {
        'renewable_codes': [],
        'landuse_codes': [],
        'verbrauch_codes': []
    }
    
    # Find VerbrauchData references
    verbrauch_pattern = r'VerbrauchData_(\d+(?:\.\d+)*)'
    dependencies['verbrauch_codes'] = re.findall(verbrauch_pattern, formula)
    
    # Find LandUse references
    landuse_pattern = r'LandUse_(\d+(?:\.\d+)*)'
    dependencies['landuse_codes'] = re.findall(landuse_pattern, formula)
    
    # Find renewable code references (numeric codes like 1.1.2.1.2)
    # Exclude codes already found in VerbrauchData_ or LandUse_ patterns
    code_pattern = r'(?<!_)(\d+(?:\.\d+)+)(?![_\d])'
    all_codes = re.findall(code_pattern, formula)
    
    # Filter out codes that are part of VerbrauchData_ or LandUse_
    dependencies['renewable_codes'] = [
        code for code in all_codes 
        if code not in dependencies['verbrauch_codes'] 
        and code not in dependencies['landuse_codes']
    ]
    
    return dependencies


def get_formula_calculation_order():
    """
    Determine the order in which formulas should be calculated to respect dependencies.
    
    Returns:
        list: List of codes in calculation order
    """
    from collections import defaultdict, deque
    
    # Build dependency graph
    graph = defaultdict(list)
    in_degree = defaultdict(int)
    
    for code, formula_def in ALL_RENEWABLE_FORMULAS.items():
        formula = formula_def.get('formula')
        if formula and not formula_def.get('is_fixed', True):
            deps = parse_formula_dependencies(formula)
            renewable_deps = deps['renewable_codes']
            
            for dep in renewable_deps:
                if dep in ALL_RENEWABLE_FORMULAS:
                    graph[dep].append(code)
                    in_degree[code] += 1
            
            # Ensure all codes are in in_degree
            if code not in in_degree:
                in_degree[code] = 0
    
    # Topological sort using Kahn's algorithm
    queue = deque([code for code in ALL_RENEWABLE_FORMULAS.keys() if in_degree[code] == 0])
    result = []
    
    while queue:
        code = queue.popleft()
        result.append(code)
        
        for dependent in graph[code]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)
    
    return result


# =============================================================================
# DJANGO MANAGEMENT COMMAND SUPPORT
# =============================================================================

def print_formula_summary():
    """
    Print a summary of all formulas in the registry.
    """
    print("=" * 80)
    print("RENEWABLE ENERGY FORMULA REGISTRY")
    print("=" * 80)
    print(f"\nTotal formulas: {len(ALL_RENEWABLE_FORMULAS)}")
    
    for section in range(1, 10):
        formulas = get_formulas_by_section(section)
        if formulas:
            print(f"  Section {section}: {len(formulas)} formulas")
    
    print("\n" + "=" * 80)


if __name__ == '__main__':
    # If run directly, print summary
    print_formula_summary()
