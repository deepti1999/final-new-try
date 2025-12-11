"""
Verbrauch Calculator - Database-Driven Energy Consumption Calculations
=====================================================================

UPDATED: Now loads formulas from database via FormulaService.
Falls back to Python files (verbrauch_calculations.py) for backward compatibility.

This provides:
- Editable formulas via Django Admin
- Real-time formula updates without code changes
- Versioning and validation
- Backward compatibility with existing calculation methods
"""

from .formula_evaluator import FormulaEvaluator
from simulator.formula_service import FormulaService


class VerbrauchCalculator:
    """
    Calculator for energy consumption (Verbrauch) data.
    Now uses FormulaService to load formulas from database.
    """
    
    def __init__(self):
        self.evaluator = FormulaEvaluator()
        self.formula_service = FormulaService(use_cache=True)
        self.cache = {}
    
    def set_data_sources(self, verbrauch_data, renewable_data=None, landuse_data=None):
        """
        Set up lookup dictionaries from data sources.
        
        Args:
            verbrauch_data: Dict of {code: {'status': x, 'ziel': y}}
            renewable_data: Optional dict of renewable data
            landuse_data: Optional dict of landuse data
        """
        # Clear cache when new data sources are set
        self.cache = {}
        
        status_lookup = {}
        target_lookup = {}
        
        # Add VerbrauchData with Verbrauch_ prefix to match formula references
        for code, data in verbrauch_data.items():
            verbrauch_key = f'Verbrauch_{code}'
            if data.get('status') is not None:
                status_lookup[verbrauch_key] = float(data['status'])
            if data.get('ziel') is not None:
                target_lookup[verbrauch_key] = float(data['ziel'])
        
        # Add RenewableData if provided
        if renewable_data:
            for code, data in renewable_data.items():
                renewable_key = f'Renewable_{code}'
                if data.get('status_value') is not None:
                    status_lookup[renewable_key] = float(data['status_value'])
                if data.get('target_value') is not None:
                    target_lookup[renewable_key] = float(data['target_value'])
        
        # Add LandUse if provided
        if landuse_data:
            for code, data in landuse_data.items():
                landuse_key = f'LandUse_{code}'
                if data.get('status_ha') is not None:
                    status_lookup[landuse_key] = float(data['status_ha'])
                if data.get('target_ha') is not None:
                    target_lookup[landuse_key] = float(data['target_ha'])
        
        self.evaluator.set_lookups(status_lookup, target_lookup)
    
    def calculate(self, code):
        """
        Calculate status and ziel values for a verbrauch item.
        Now loads formula from database via FormulaService.
        
        Args:
            code: The verbrauch code (e.g., 'V_1.2.1')
            
        Returns:
            tuple: (status, ziel) values or (None, None) if fixed or error
        """
        # Get formula from database first
        formula_def = self.formula_service.get_formula(code, category='verbrauch')
        
        if not formula_def:
            # No formula in database
            return None, None
        
        # If fixed value, return None (use database values)
        if formula_def.get('is_fixed'):
            return None, None
        
        formula = formula_def.get('expression')
        if not formula:
            return None, None
        
        # Check cache
        if code in self.cache:
            return self.cache[code]
        
        # Handle simple direct references
        if self._is_simple_reference(formula):
            result = self._get_simple_reference_values(formula)
            self.cache[code] = result
            return result
        
        # Calculate using formula evaluator
        status_value = self.evaluator.evaluate(formula, use_target=False)
        ziel_value = self.evaluator.evaluate(formula, use_target=True)
        
        result = (status_value, ziel_value)
        self.cache[code] = result
        return result
    
    def _is_simple_reference(self, formula):
        """Check if formula is a simple code reference"""
        return (
            formula and
            not any(op in formula for op in ['+', '-', '*', '/', '(', ')']) and
            ('.' in formula or formula.startswith('Verbrauch_') or 
             formula.startswith('Renewable_') or formula.startswith('LandUse_'))
        )
    
    def _get_simple_reference_values(self, formula):
        """Get values for simple code references"""
        if formula.startswith('Verbrauch_'):
            lookup_key = formula
        elif formula.startswith('Renewable_'):
            lookup_key = formula
        elif formula.startswith('LandUse_'):
            lookup_key = formula
        else:
            # Standalone code - default to Verbrauch namespace
            lookup_key = f'Verbrauch_{formula}'
        
        status = self.evaluator.status_lookup.get(lookup_key)
        ziel = self.evaluator.target_lookup.get(lookup_key)
        return (status, ziel)
    
    def get_formula(self, code):
        """
        Get the formula for a code.
        Loads from database.
        """
        formula_def = self.formula_service.get_formula(code, category='verbrauch')
        if formula_def:
            return formula_def.get('expression')
        return None
    
    def is_fixed(self, code):
        """
        Check if a code is a fixed value.
        Loads from database.
        """
        formula_def = self.formula_service.get_formula(code, category='verbrauch')
        if formula_def:
            return formula_def.get('is_fixed', True)
        return True
    
    def get_effective_value(self, verbrauch_item):
        """
        Get the effective value considering all calculations.
        
        Args:
            verbrauch_item: The VerbrauchData object
            
        Returns:
            float: The calculated or stored value
        """
        # Check if this item has a formula
        if hasattr(verbrauch_item, 'code'):
            formula_key = f'V_{verbrauch_item.code}'
            if not self.is_fixed(formula_key):
                status, _ = self.calculate(formula_key)
                if status is not None:
                    return status
        
        # Return stored value
        return verbrauch_item.status if hasattr(verbrauch_item, 'status') else None
    
    def get_effective_ziel_value(self, verbrauch_item):
        """
        Get the effective target value considering all calculations.
        
        Args:
            verbrauch_item: The VerbrauchData object
            
        Returns:
            float: The calculated or stored target value
        """
        # Check if this item has a formula
        if hasattr(verbrauch_item, 'code'):
            formula_key = f'V_{verbrauch_item.code}'
            if not self.is_fixed(formula_key):
                _, ziel = self.calculate(formula_key)
                if ziel is not None:
                    return ziel
        
        # Return stored value
        return verbrauch_item.ziel if hasattr(verbrauch_item, 'ziel') else None

