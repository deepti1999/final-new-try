"""
Formula Service - Database-Driven Formula Management
====================================================

This service provides a centralized way to load and manage formulas.
It implements a hybrid approach:
1. Load from database first (if available)
2. Fall back to Python files for backward compatibility
3. Cache for performance

ENHANCED FEATURES:
- Database-first formula loading
- Fallback to Python files (renewable_energy_complete_formulas.py)
- Caching for performance
- Formula validation
- Version control support
"""

from typing import Dict, Optional, List
from django.db import models
from django.core.cache import cache
from django.utils import timezone
import logging

from simulator.models import (
    Formula,
    FormulaVariable,
    LandUse,
    RenewableData,
    VerbrauchData,
)

logger = logging.getLogger(__name__)


def evaluate_formula_by_key(formula_key: str, extra_context: Optional[Dict] = None) -> Optional[float]:
    """
    Evaluate a formula by its key using FormulaVariable mappings to resolve inputs.

    Returns:
        float or None if not found/failed.
    """
    formula = Formula.objects.filter(key=formula_key).prefetch_related("variables").first()
    if not formula:
        return None

    context = _build_context(formula)
    if extra_context:
        context.update(extra_context)

    try:
        return _safe_eval(formula.expression, context)
    except Exception as exc:  # pragma: no cover - defensive guard
        print(f"❌ Error evaluating formula '{formula_key}': {exc}")
        return None


def _build_context(formula: Formula) -> Dict[str, float]:
    """Resolve all variables for a formula into a plain dict."""
    context: Dict[str, float] = {}
    for var in formula.variables.all():
        resolved = _resolve_variable(var)
        if resolved is None:
            resolved = var.default_value
        if resolved is None:
            # No value available; use 0 to keep evaluation resilient
            resolved = 0
        context[var.variable_name] = resolved
    return context


def _resolve_variable(var: FormulaVariable) -> Optional[float]:
    """Resolve a single FormulaVariable to a numeric value."""
    source_key = var.source_key

    if var.source_type == FormulaVariable.LITERAL:
        try:
            return float(source_key)
        except (TypeError, ValueError):
            return None

    if var.source_type == FormulaVariable.LANDUSE_STATUS:
        return _get_value(LandUse, "code", source_key, "status_ha")
    if var.source_type == FormulaVariable.LANDUSE_TARGET:
        return _get_value(LandUse, "code", source_key, "target_ha")
    if var.source_type == FormulaVariable.RENEWABLE_STATUS:
        return _get_value(RenewableData, "code", source_key, "status_value")
    if var.source_type == FormulaVariable.RENEWABLE_TARGET:
        return _get_value(RenewableData, "code", source_key, "target_value")
    if var.source_type == FormulaVariable.VERBRAUCH_STATUS:
        return _get_value(VerbrauchData, "code", source_key, "status")
    if var.source_type == FormulaVariable.VERBRAUCH_ZIEL:
        return _get_value(VerbrauchData, "code", source_key, "ziel")

    return None


def _get_value(model: models.Model, lookup_field: str, lookup_value: str, value_field: str) -> Optional[float]:
    """Helper to fetch a numeric field from a model instance."""
    try:
        obj = model.objects.only(value_field).get(**{lookup_field: lookup_value})
        return getattr(obj, value_field)
    except model.DoesNotExist:
        return None
    except Exception:
        return None


def _safe_eval(expression: str, names: Dict[str, float]) -> Optional[float]:
    """
    Evaluate a simple math expression safely using a controlled names dict.
    Supports +, -, *, /, parentheses, and basic helpers (max/min/abs).
    """
    allowed_funcs = {"max": max, "min": min, "abs": abs}
    scope = {"__builtins__": {}}
    scope.update(allowed_funcs)
    scope.update(names)
    result = eval(expression, scope, {})
    return float(result)


# =============================================================================
# ENHANCED FORMULA SERVICE - Database-First with Python Fallback
# =============================================================================

class FormulaService:
    """
    Centralized formula management service.
    Loads formulas from database with fallback to Python files.
    """
    
    CACHE_PREFIX = 'formula_'
    CACHE_TIMEOUT = 300  # 5 minutes
    
    def __init__(self, use_cache=True):
        """
        Initialize the formula service.
        
        Args:
            use_cache: Whether to use Django cache for formulas
        """
        self.use_cache = use_cache
        self._python_formulas_loaded = False
        self._python_formulas_cache = {}
    
    def get_formula(self, key: str, category: str = 'renewable') -> Optional[Dict]:
        """
        Get formula definition by key.
        
        Args:
            key: Formula key (e.g., '1.1.2.1.2')
            category: Formula category (renewable, verbrauch, landuse, etc.)
            
        Returns:
            Dictionary with formula details or None if not found
        """
        # Try cache first
        if self.use_cache:
            cached = cache.get(f'{self.CACHE_PREFIX}{key}')
            if cached is not None:
                return cached
        
        # Try database
        formula = self._get_from_database(key, category)
        if formula:
            if self.use_cache:
                cache.set(f'{self.CACHE_PREFIX}{key}', formula, self.CACHE_TIMEOUT)
            return formula
        
        # Fall back to Python files
        formula = self._get_from_python_files(key)
        if formula and self.use_cache:
            cache.set(f'{self.CACHE_PREFIX}{key}', formula, self.CACHE_TIMEOUT)
        
        return formula
    
    def _get_from_database(self, key: str, category: str) -> Optional[Dict]:
        """Load formula from database"""
        try:
            formula_obj = Formula.objects.filter(
                key=key,
                is_active=True
            ).first()
            
            if formula_obj:
                return {
                    'key': formula_obj.key,
                    'expression': formula_obj.expression,
                    'description': formula_obj.description,
                    'is_active': formula_obj.is_active,
                    'is_fixed': formula_obj.is_fixed,
                    'category': formula_obj.category,
                    'version': formula_obj.version,
                    'validation_status': formula_obj.validation_status,
                }
        except Exception as e:
            logger.warning(f"Error loading formula {key} from database: {e}")
        
        return None
    
    def _get_from_python_files(self, key: str) -> Optional[Dict]:
        """
        Load formula from Python files (backward compatibility).
        Falls back to renewable_energy_complete_formulas.py
        """
        if not self._python_formulas_loaded:
            self._load_python_formulas()
        
        return self._python_formulas_cache.get(key)
    
    def _load_python_formulas(self):
        """Load all formulas from Python files into cache"""
        try:
            import sys
            import os
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            
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
            
            # Combine all sections
            all_formulas = {
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
            
            # Convert to standardized format
            for code, formula_def in all_formulas.items():
                self._python_formulas_cache[code] = {
                    'key': code,
                    'expression': formula_def.get('formula'),
                    'description': formula_def.get('description', ''),
                    'is_active': True,
                    'is_fixed': formula_def.get('is_fixed', False),
                    'category': 'renewable',
                    'version': 1,
                    'validation_status': 'valid',
                }
            
            self._python_formulas_loaded = True
            logger.info(f"Loaded {len(self._python_formulas_cache)} formulas from Python files")
            
        except ImportError as e:
            logger.warning(f"Could not load Python formula files: {e}")
            self._python_formulas_loaded = True  # Mark as loaded to avoid retry
    
    def get_all_formulas(self, category: Optional[str] = None, active_only: bool = True) -> List[Dict]:
        """
        Get all formulas, optionally filtered by category.
        
        Args:
            category: Filter by category (renewable, verbrauch, etc.)
            active_only: Only return active formulas
            
        Returns:
            List of formula dictionaries
        """
        formulas = []
        
        # Get from database first
        try:
            queryset = Formula.objects.all()
            if active_only:
                queryset = queryset.filter(is_active=True)
            if category:
                queryset = queryset.filter(category=category)
            
            for formula_obj in queryset:
                formulas.append({
                    'key': formula_obj.key,
                    'expression': formula_obj.expression,
                    'description': formula_obj.description,
                    'is_active': formula_obj.is_active,
                    'is_fixed': formula_obj.is_fixed,
                    'category': formula_obj.category,
                    'version': formula_obj.version,
                    'validation_status': formula_obj.validation_status,
                })
        except Exception as e:
            logger.warning(f"Error loading formulas from database: {e}")
        
        # If no database formulas, load from Python files
        if not formulas:
            if not self._python_formulas_loaded:
                self._load_python_formulas()
            
            for formula in self._python_formulas_cache.values():
                if category and formula.get('category') != category:
                    continue
                if active_only and not formula.get('is_active'):
                    continue
                formulas.append(formula)
        
        return formulas
    
    def save_formula(self, key: str, expression: str, description: str = '', 
                    category: str = 'renewable', is_fixed: bool = False) -> bool:
        """
        Save or update a formula in the database.
        
        Args:
            key: Formula key
            expression: Formula expression
            description: Human-readable description
            category: Formula category
            is_fixed: Whether this is a fixed value
            
        Returns:
            True if successful, False otherwise
        """
        try:
            formula, created = Formula.objects.update_or_create(
                key=key,
                defaults={
                    'expression': expression,
                    'description': description,
                    'category': category,
                    'is_fixed': is_fixed,
                    'is_active': True,
                    'validation_status': 'pending',
                }
            )
            
            if not created:
                formula.increment_version()
            
            # Invalidate cache
            if self.use_cache:
                cache.delete(f'{self.CACHE_PREFIX}{key}')
            
            logger.info(f"{'Created' if created else 'Updated'} formula {key}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving formula {key}: {e}")
            return False
    
    def clear_cache(self):
        """Clear all cached formulas"""
        if self.use_cache:
            try:
                cache.delete_pattern(f'{self.CACHE_PREFIX}*')
            except:
                # Fallback for cache backends that don't support delete_pattern
                pass
        
        # Clear internal Python formulas cache
        self._python_formulas_cache.clear()
        self._python_formulas_loaded = False
        
        logger.info("Formula cache cleared")


# Global instance for easy access
_formula_service = None

def get_formula_service() -> FormulaService:
    """Get or create global FormulaService instance"""
    global _formula_service
    if _formula_service is None:
        _formula_service = FormulaService()
    return _formula_service
