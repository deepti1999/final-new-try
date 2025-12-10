from django.db import models
from typing import Optional

# ALL FORMULAS ARE STORED IN DATABASE (simulator_renewabledata.formula column)
# No external Python files are used for formula storage

# Import WS Data model
from .ws_models import WSData

class LandUse(models.Model):
    code = models.CharField(max_length=20)  # e.g. "2.2.1"
    name = models.CharField(max_length=255)  # Clean name from CSV
    
    # Store hectare values from CSV
    status_ha = models.FloatField(null=True, blank=True)       # Status_ha from CSV
    target_ha = models.FloatField(null=True, blank=True)       # Target_ha from CSV
    
    # User input for custom percentage calculations
    user_percent = models.FloatField(null=True, blank=True, help_text="User-defined percentage for target calculations")
    target_locked = models.BooleanField(default=False, help_text="Preserve manual target_ha edits from parent cascades")
    
    # Hierarchical relationship - will be set from Parent_Code in CSV
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='children')
    
    # Meta information
    quelle = models.CharField(max_length=100, null=True, blank=True)  # Quelle (reference)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name}"
    
    def save(self, *args, **kwargs):
        """
        Override save to trigger cascade updates in RenewableData when LandUse values change.
        
        CASCADE UPDATE SYSTEM FOR LANDUSE:
        - When status_ha or target_ha changes, finds all RenewableData items that reference this LandUse code
        - Automatically recalculates dependent renewable energy values
        - Example: LandUse 2.1 (Wind area) → RenewableData 2.1.1 (Wind production)
        """
        skip_cascade = kwargs.pop('skip_cascade', False)
        force_recalc = kwargs.pop('force_recalc', False)
        old_status_ha = None
        old_target_ha = None
        
        # Track old values for change detection
        if self.pk:
            try:
                old_obj = LandUse.objects.get(pk=self.pk)
                old_status_ha = old_obj.status_ha
                old_target_ha = old_obj.target_ha
            except LandUse.DoesNotExist:
                pass
        
        # AUTO-ASSIGN PARENT if missing but code indicates a parent relationship
        # Example: LU_1.1 → parent = LU_1, LU_1.2.3 → parent = LU_1.2
        if self.parent is None and self.code and "." in self.code:
            parent_code = ".".join(self.code.split(".")[:-1])
            try:
                self.parent = LandUse.objects.get(code=parent_code)
                print(f"✅ Auto-assigned parent: {self.code} → {parent_code}")
            except LandUse.DoesNotExist:
                print(f"⚠️ Parent {parent_code} not found for {self.code}")
                pass
        
        # Check if target_ha was manually changed (direct database edit)
        target_ha_manually_changed = (old_target_ha is not None and 
                                       self.target_ha is not None and 
                                       old_target_ha != self.target_ha)
        
        # PRIORITY 1: If target_ha was manually changed, DON'T recalculate it, just calculate target_percent
        if target_ha_manually_changed:
            if self.parent and self.parent.target_ha and self.parent.target_ha > 0:
                try:
                    self.target_percent = (self.target_ha / self.parent.target_ha) * 100.0
                    print(f"✅ Manual target_ha change detected for {self.code}: {self.target_ha:.2f} ha → {self.target_percent:.2f}%")
                except:
                    pass
            # Lock manual target so parent cascades do not overwrite
            self.target_locked = True
        # PRIORITY 2: If user_percent changed (NOT target_ha), calculate target_ha from it
        elif self.user_percent is not None and self.parent and self.parent.target_ha and (force_recalc or not self.target_locked):
            try:
                # Only recalculate if we're coming from the frontend user_percent input
                # Not when manually editing target_ha in admin
                self.target_ha = (self.parent.target_ha * self.user_percent) / 100.0
                # Also set target_percent to match user_percent
                self.target_percent = self.user_percent
                # Lock this value so later parent cascades don't overwrite the explicit user-set percent result
                self.target_locked = True
            except:
                pass
        
        # Save the current object first
        super(LandUse, self).save(*args, **kwargs)
        
        # Cascade updates to dependent RenewableData if values changed and cascade not disabled
        if not skip_cascade and self.code:
            status_ha_changed = old_status_ha != self.status_ha
            target_ha_changed = old_target_ha != self.target_ha
            
            if status_ha_changed or target_ha_changed:
                # Update renewable energy data that references this LandUse
                self._recalculate_renewable_dependents()
            
            # Cascade to children - but only if user_percent changed, not if target_ha manually edited
            if target_ha_changed and not target_ha_manually_changed:
                self._cascade_to_children()
    
    def _recalculate_renewable_dependents(self):
        """
        Find and recalculate all RenewableData items that reference this LandUse code.
        This is called automatically when LandUse values change.
        
        CASCADE MECHANISM:
        1. Find all RenewableData with formulas like "LandUse_X.X"
        2. Recalculate those items with fresh data
        3. Those items will trigger their own cascades in RenewableData
        """
        if not self.code:
            return
        
        # Import here to avoid circular dependency
        import re
        
        # Find all RenewableData items that reference this LandUse code
        # Pattern: "LandUse_LU_X.X" where LU_X.X is the code (with LU_ prefix)
        # Don't escape - we want exact string match
        landuse_pattern = f"LandUse_{self.code}"
        # Some formulas omit the LU_ prefix (e.g., LandUse_2.1); support both
        alt_landuse_pattern = None
        if self.code.startswith("LU_"):
            alt_landuse_pattern = f"LandUse_{self.code.replace('LU_', '')}"
        
        # Get all calculated RenewableData items
        dependent_items = RenewableData.objects.filter(
            formula__isnull=False
        )
        
        updated_count = 0
        # Build lookup tables ONCE before the loop
        # This avoids including items we're about to update in the lookup
        status_lookup = {}
        target_lookup = {}
        
        # Add all LandUse data with LandUse_ prefix to match formula references
        # Formulas use "LandUse_LU_2.1" format, so we need to store with that key
        for landuse in LandUse.objects.all():
            # Use LandUse_ prefix to match formula format (e.g., "LandUse_LU_2.1")
            prefixed_key = f'LandUse_{landuse.code}'
            stripped_key = f"LandUse_{landuse.code.replace('LU_', '')}"
            if landuse.status_ha is not None:
                status_lookup[prefixed_key] = float(landuse.status_ha)
                status_lookup[stripped_key] = float(landuse.status_ha)
            if landuse.target_ha is not None:
                target_lookup[prefixed_key] = float(landuse.target_ha)
                target_lookup[stripped_key] = float(landuse.target_ha)
        
        # Add all RenewableData values (these will be overridden as we update items)
        for renewable in RenewableData.objects.all():
            if renewable.status_value is not None:
                status_lookup[renewable.code] = float(renewable.status_value)
            if renewable.target_value is not None:
                target_lookup[renewable.code] = float(renewable.target_value)
        
        for item in dependent_items:
            if item.formula and (landuse_pattern in item.formula or (alt_landuse_pattern and alt_landuse_pattern in item.formula)):
                try:
                    calc_status, calc_target = item.get_calculated_values(
                        _cache={},
                        status_lookup=status_lookup,
                        target_lookup=target_lookup
                    )
                    
                    values_changed = False
                    if calc_status is not None and item.status_value != calc_status:
                        item.status_value = calc_status
                        values_changed = True
                    
                    if calc_target is not None and item.target_value != calc_target:
                        item.target_value = calc_target
                        values_changed = True
                    
                    if values_changed:
                        # Avoid triggering full Verbrauch recalculation for every dependent during LandUse cascades
                        item.save(skip_verbrauch_recalc=True)
                        
                        # 🔥 CRITICAL FIX: update lookup so next items see new values
                        status_lookup[item.code] = item.status_value
                        target_lookup[item.code] = item.target_value
                        
                        updated_count += 1
                
                except Exception as e:
                    print(f"❌ Error recalculating RenewableData {item.code} from LandUse {self.code}: {str(e)}")
                    import traceback
                    traceback.print_exc()
        
        # Silent by default - set settings.LOG_CASCADE_UPDATES = True to enable logging
        pass
    
    def _cascade_to_children(self):
        """
        When this LandUse item's target_ha changes, cascade the update to all children.
        Children will recalculate their target_ha based on their user_percent and new parent value.
        
        Example: If LU_1 target_ha changes from 100 to 200:
        - LU_1.1 has user_percent=20% → target_ha becomes 200 * 20% = 40
        - LU_1.2 has user_percent=30% → target_ha becomes 200 * 30% = 60
        """
        # Get all direct children of this item
        children = LandUse.objects.filter(parent=self)
        
        for child in children:
            # Only update if child has a user_percent set
            if child.user_percent is not None and self.target_ha is not None and not child.target_locked:
                try:
                    # Recalculate child's target_ha based on new parent value
                    old_child_target = child.target_ha
                    child.target_ha = (self.target_ha * child.user_percent) / 100.0
                    
                    # Save child (this will trigger its own cascade to grandchildren)
                    child.save()
                    
                    print(f"🔄 Cascaded: {child.code} target_ha: {old_child_target} → {child.target_ha}")
                except Exception as e:
                    print(f"❌ Error cascading to child {child.code}: {str(e)}")


class RenewableData(models.Model):
    """
    Unified model for all renewable energy data types
    Flexible structure to handle Solar, Wind, Water, Biomass, etc.
    """
    # Main categorization
    category = models.CharField(max_length=50)  # Solar, Wind, Water, Biomass, etc.
    subcategory = models.CharField(max_length=100, blank=True, null=True)  # e.g. "Photovoltaik", "Onshore", etc.
    
    # Identification
    code = models.CharField(max_length=20, blank=True, null=True)  # Optional code for ordering
    name = models.CharField(max_length=200)  # e.g. "Bruttostromerzeugung", "Anlagenanzahl"
    description = models.TextField(blank=True, null=True)  # Additional details
    
    # Data values
    unit = models.CharField(max_length=20)  # ha, %, GWh/a, MW, Anzahl, etc.
    status_value = models.FloatField(null=True, blank=True)  # Current/existing value
    target_value = models.FloatField(null=True, blank=True)  # Future target value
    
    # User interaction
    user_input = models.FloatField(null=True, blank=True)  # User-defined value
    formula = models.TextField(blank=True, null=True)  # Calculation formula (e.g. "M6*M8*M9/1000")
    
    # New fields for enhanced structure
    is_fixed = models.BooleanField(default=True)  # Whether value is fixed (YES) or calculated (NO)
    parent_code = models.CharField(max_length=20, blank=True, null=True)  # Parent hierarchical reference
    
    # Metadata
    source = models.CharField(max_length=100, blank=True, null=True)  # Data source reference
    notes = models.TextField(blank=True, null=True)  # Additional notes
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['category', 'subcategory', 'code', 'name']
        indexes = [
            models.Index(fields=['category']),
            models.Index(fields=['category', 'subcategory']),
        ]
    
    def __str__(self):
        if self.subcategory:
            return f"{self.category} - {self.subcategory} - {self.name}"
        return f"{self.category} - {self.name}"
    
    def save(self, *args, **kwargs):
        """
        Override save to recalculate dependent formulas when ANY value changes.
        This ensures that when you edit ANY value (fixed or calculated), all items
        that depend on it automatically update their calculated values.
        
        CASCADE UPDATE SYSTEM:
        - When a fixed value changes (e.g., 2.1.1.1), all formulas using it recalculate
        - When a calculated value changes, its dependents also recalculate
        - Prevents infinite recursion by tracking update chain
        - Updates happen immediately without manual intervention
        """
        # Track if values actually changed to avoid unnecessary cascades
        skip_cascade = kwargs.pop('skip_cascade', False)
        skip_verbrauch_recalc = kwargs.pop('skip_verbrauch_recalc', False)
        # Hint to post_save signal to optionally skip heavy Verbrauch recalc when cascading LandUse updates
        self._skip_verbrauch_recalc = skip_verbrauch_recalc
        old_status = None
        old_target = None
        
        if self.pk:  # Only check for existing records
            try:
                old_obj = RenewableData.objects.get(pk=self.pk)
                old_status = old_obj.status_value
                old_target = old_obj.target_value
            except RenewableData.DoesNotExist:
                pass
        
        # Save the current object first
        super().save(*args, **kwargs)
        
        # Cascade updates to dependents if values changed and cascade not disabled
        if not skip_cascade and self.code:
            status_changed = old_status != self.status_value
            target_changed = old_target != self.target_value
            
            if status_changed or target_changed:
                self._recalculate_dependents()

        # Reset skip flag after save to avoid leaking into unrelated operations
        self._skip_verbrauch_recalc = False
    
    def _recalculate_dependents(self):
        """
        Find and recalculate all RenewableData items that reference this code in their formulas.
        This is called automatically when ANY value changes (fixed or calculated).
        Uses the centralized calculation_engine for all calculations.
        
        CASCADE MECHANISM:
        1. Find all items with formulas referencing this code
        2. Load fresh data from all sources (LandUse, VerbrauchData, RenewableData)
        3. Use calculation_engine.RenewableCalculator to recalculate values
        4. Save with skip_cascade=False to trigger further cascades
        5. Builds complete dependency chain automatically
        """
        if not self.code:
            return
        
        # Find all items that have formulas referencing this code
        import re
        pattern = r'\b' + re.escape(self.code) + r'\b'
        
        dependent_items = RenewableData.objects.filter(
            is_fixed=False,
            formula__isnull=False
        ).exclude(code=self.code)
        
        # Find items that actually depend on this code
        items_to_update = []
        for item in dependent_items:
            if item.formula and re.search(pattern, item.formula):
                items_to_update.append(item)
        
        if not items_to_update:
            return
        
        try:
            # Import calculation engine
            import sys
            import os
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from calculation_engine.renewable_engine import RenewableCalculator
            from simulator.models import LandUse, VerbrauchData
            
            # Initialize calculator with fresh data
            calculator = RenewableCalculator()
            
            # Load all data sources (keys without prefix, prefixes added inside set_data_sources)
            landuse_data = {
                i.code: {'status_ha': i.status_ha or 0, 'target_ha': i.target_ha or 0}
                for i in LandUse.objects.all()
            }
            verbrauch_data = {
                i.code: {'status': i.status or 0, 'ziel': i.ziel or 0}
                for i in VerbrauchData.objects.all()
            }
            renewable_data = {
                i.code: {'status_value': i.status_value or 0, 'target_value': i.target_value or 0}
                for i in RenewableData.objects.all()
            }
            
            calculator.set_data_sources(landuse_data, verbrauch_data, renewable_data)
            
            # Recalculate each dependent item
            for item in items_to_update:
                try:
                    calc_status, calc_target = calculator.calculate(item.code)
                    
                    if calc_status is not None and calc_target is not None:
                        # Check if values changed
                        status_changed = abs((item.status_value or 0) - calc_status) > 0.01
                        target_changed = abs((item.target_value or 0) - calc_target) > 0.01
                        
                        if status_changed or target_changed:
                            item.status_value = calc_status
                            item.target_value = calc_target
                            # Save and trigger cascade
                            super(RenewableData, item).save(update_fields=['status_value', 'target_value', 'updated_at'])
                            item._recalculate_dependents()
                        
                except Exception as e:
                    print(f"❌ Error recalculating {item.code}: {str(e)}")
                    
        except Exception as e:
            print(f"❌ Error in cascade calculation: {str(e)}")
        
        # Cascade complete - silent by default
        # Set settings.LOG_CASCADE_UPDATES = True to enable logging
        pass
    
    def get_effective_value(self):
        """
        Return the most relevant value:
        1. User input (if provided)
        2. Calculated value (if not fixed and has formula)
        3. Target value (if available) 
        4. Status value (fallback)
        """
        if self.user_input is not None:
            return self.user_input
        
        # If not fixed and has formula, use calculated values
        if not self.is_fixed and self.formula:
            calc_status, calc_target = self.get_calculated_values()
            if calc_target is not None:
                return calc_target
            elif calc_status is not None:
                return calc_status
        
        # Fallback to stored values
        if self.target_value is not None:
            return self.target_value
        return self.status_value
    
    def has_user_modification(self):
        """Check if user has provided input"""
        return self.user_input is not None
    
    def get_calculated_values(self, _cache=None, status_lookup=None, target_lookup=None):
        """
        Calculate status_value and target_value from formula if not fixed.
        NOW USES CALCULATION ENGINE - centralized formula management.
        Returns tuple: (status_value, target_value)
        
        _cache: deprecated parameter (kept for compatibility)
        status_lookup: optional dict with updated values (used during cascade updates)
        target_lookup: optional dict with updated values (used during cascade updates)
        """
        if self.is_fixed or not self.formula:
            return self.status_value, self.target_value
        
        # Use calculation engine for all calculations
        try:
            import sys
            import os
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from calculation_engine.renewable_engine import RenewableCalculator
            from simulator.models import LandUse, VerbrauchData
            
            calculator = RenewableCalculator()
            
            # If lookups provided, use them (for cascade updates with latest values)
            # Otherwise fetch fresh from database
            if status_lookup is not None and target_lookup is not None:
                # Extract LandUse data from lookups (keys with LandUse_ prefix)
                landuse_data = {}
                for key, value in status_lookup.items():
                    if key.startswith('LandUse_'):
                        code = key.replace('LandUse_', '')
                        if code not in landuse_data:
                            landuse_data[code] = {}
                        landuse_data[code]['status_ha'] = value
                
                for key, value in target_lookup.items():
                    if key.startswith('LandUse_'):
                        code = key.replace('LandUse_', '')
                        if code not in landuse_data:
                            landuse_data[code] = {}
                        landuse_data[code]['target_ha'] = value
                
                # Extract RenewableData from lookups
                renewable_data = {}
                for key, value in status_lookup.items():
                    if not key.startswith('LandUse_'):
                        if key not in renewable_data:
                            renewable_data[key] = {}
                        renewable_data[key]['status_value'] = value
                
                for key, value in target_lookup.items():
                    if not key.startswith('LandUse_'):
                        if key not in renewable_data:
                            renewable_data[key] = {}
                        renewable_data[key]['target_value'] = value
                
                # Get VerbrauchData from DB (doesn't change during LandUse cascade)
                verbrauch_data = {
                    i.code: {'status': i.status or 0, 'ziel': i.ziel or 0}
                    for i in VerbrauchData.objects.all()
                }
            else:
                # Load all data sources from database
                landuse_data = {
                    i.code: {'status_ha': i.status_ha or 0, 'target_ha': i.target_ha or 0}
                    for i in LandUse.objects.all()
                }
                verbrauch_data = {
                    i.code: {'status': i.status or 0, 'ziel': i.ziel or 0}
                    for i in VerbrauchData.objects.all()
                }
                renewable_data = {
                    i.code: {'status_value': i.status_value or 0, 'target_value': i.target_value or 0}
                    for i in RenewableData.objects.all()
                }
            
            calculator.set_data_sources(landuse_data, verbrauch_data, renewable_data)
            
            # Calculate using engine
            calc_status, calc_target = calculator.calculate(self.code)
            
            if calc_status is not None and calc_target is not None:
                return calc_status, calc_target
            else:
                return self.status_value, self.target_value
                
        except Exception as e:
            print(f"Error in get_calculated_values for {self.code}: {e}")
            return self.status_value, self.target_value


class VerbrauchData(models.Model):
    """
    Energy Consumption Data (Verbrauch) Model
    Based on KLIK_Hierarchy_BlankForCalculated.csv structure
    Handles energy consumption categories and subcategories with hierarchical codes
    """
    # Hierarchical identification
    code = models.CharField(max_length=20, unique=True)  # e.g. "1", "1.1", "1.1.1", etc.
    category = models.CharField(max_length=200)  # Energy consumption category description
    
    # Data values
    unit = models.CharField(max_length=20)  # GWh/a, %, etc.
    status = models.FloatField(null=True, blank=True)  # Current status value
    ziel = models.FloatField(null=True, blank=True)  # Target value (Ziel)
    
    # Calculation control
    is_calculated = models.BooleanField(default=False)  # True if this should be calculated via formula
    status_calculated = models.BooleanField(default=False)  # True if STATUS should be calculated
    ziel_calculated = models.BooleanField(default=False)  # True if ZIEL should be calculated
    
    # User interaction (for future functionality)
    user_percent = models.FloatField(null=True, blank=True)  # User-defined percentage
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['code']
        indexes = [
            models.Index(fields=['code']),
        ]
    
    def __str__(self):
        return f"{self.code} - {self.category}"
    
    def save(self, *args, **kwargs):
        """
        Override save to automatically calculate values for calculated fields.
        Enhanced with CASCADE UPDATE SYSTEM:
        - Recalculates own values if marked as calculated
        - Triggers recalculation of all dependent VerbrauchData entries
        - Prevents infinite recursion by tracking update chain
        - Updates happen immediately when any value changes
        """
        skip_cascade = kwargs.pop('skip_cascade', False)
        skip_recalc = kwargs.pop('skip_recalc', False)
        old_status = None
        old_ziel = None
        
        # Track old values for change detection
        if self.pk:
            try:
                old_obj = VerbrauchData.objects.get(pk=self.pk)
                old_status = old_obj.status
                old_ziel = old_obj.ziel
            except VerbrauchData.DoesNotExist:
                pass
        
        # Calculate values if this is a calculated field
        if self.is_calculated or self.status_calculated or self.ziel_calculated:
            try:
                if self.status_calculated or self.is_calculated:
                    calculated_status = self.calculate_value()
                    if calculated_status is not None:
                        self.status = calculated_status
                
                if self.ziel_calculated or self.is_calculated:
                    calculated_ziel = self.calculate_ziel_value()
                    if calculated_ziel is not None:
                        self.ziel = calculated_ziel
            except Exception as e:
                # Log error but don't fail the save
                print(f"Error calculating values for {self.code}: {str(e)}")
        
        super(VerbrauchData, self).save(*args, **kwargs)
        
        # Cascade updates to dependents if values changed and cascade not disabled
        if not skip_cascade and self.code:
            status_changed = old_status != self.status
            ziel_changed = old_ziel != self.ziel
            
            if status_changed or ziel_changed:
                self._recalculate_dependents()

        # Ensure broader recalculation/rollups occur after any save that changes a Verbrauch row
        if not skip_recalc:
            try:
                from simulator.verbrauch_recalculator import recalc_all_verbrauch
                recalc_all_verbrauch(trigger_code=self.code)
            except Exception as exc:  # pragma: no cover - defensive guard
                print(f"Error triggering Verbrauch recalculation for {self.code}: {exc}")
    
    def _recalculate_dependents(self):
        """
        Find and recalculate all VerbrauchData items that depend on this code.
        This is called automatically when values change.
        
        CASCADE MECHANISM FOR VERBRAUCH:
        1. Find all items that use this code in their formulas
        2. Recalculate each dependent item
        3. Save and trigger further cascades automatically
        4. Handles complex hierarchies like: 1.1 -> 1.4 -> 1 -> [top levels]
        """
        if not self.code:
            return
        
        # Import verbrauch_calculations to check which formulas use this code
        from . import verbrauch_calculations
        import re
        
        # Find all calculated items
        dependent_items = VerbrauchData.objects.filter(
            models.Q(is_calculated=True) | 
            models.Q(status_calculated=True) | 
            models.Q(ziel_calculated=True)
        ).exclude(code=self.code)
        
        updated_count = 0
        # Check each item to see if it might depend on this code
        # We check by seeing if recalculation produces different results
        for item in dependent_items:
            try:
                old_status = item.status
                old_ziel = item.ziel
                
                # Recalculate values
                new_status = None
                new_ziel = None
                
                if item.status_calculated or item.is_calculated:
                    new_status = item.calculate_value()
                    
                if item.ziel_calculated or item.is_calculated:
                    new_ziel = item.calculate_ziel_value()
                
                # Check if values changed
                values_changed = False
                if new_status is not None and old_status != new_status:
                    item.status = new_status
                    values_changed = True
                if new_ziel is not None and old_ziel != new_ziel:
                    item.ziel = new_ziel
                    values_changed = True
                
                if values_changed:
                    # Save WITH cascade to propagate changes
                    super(VerbrauchData, item).save(update_fields=['status', 'ziel', 'updated_at'])
                    # Manually trigger cascade since we used super()
                    item._recalculate_dependents()
                    updated_count += 1
                    
            except Exception as e:
                # Log error but don't fail
                print(f"❌ Error recalculating dependent VerbrauchData {item.code}: {str(e)}")
        
        if updated_count > 0:
            print(f"✅ Cascaded update: VerbrauchData {self.code} -> {updated_count} dependent(s) recalculated")
        
        # CASCADE TO RENEWABLEDATA: Find all RenewableData items that reference this VerbrauchData code
        self._recalculate_renewable_dependents()
    
    def _recalculate_renewable_dependents(self):
        """
        Find and recalculate all RenewableData items that reference this VerbrauchData code.
        This is called automatically when VerbrauchData values change.
        
        CASCADE MECHANISM:
        1. Find all RenewableData with formulas like "VerbrauchData_X" 
        2. Use calculation_engine to recalculate those items
        3. Those items will trigger their own cascades in RenewableData
        """
        if not self.code:
            return
        
        # Import here to avoid circular dependency
        import re
        
        # Pattern to find references to this VerbrauchData code
        # Can be "VerbrauchData_5" or just "Verbrauch_5" in formulas
        verbrauch_pattern = f"VerbrauchData_{self.code}"
        
        # Get all calculated RenewableData items
        dependent_items = RenewableData.objects.filter(
            is_fixed=False,
            formula__isnull=False
        )
        
        # Find items that reference this VerbrauchData
        items_to_update = []
        for item in dependent_items:
            if item.formula and verbrauch_pattern in item.formula:
                items_to_update.append(item)
        
        if not items_to_update:
            return
        
        try:
            # Import calculation engine
            import sys
            import os
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from calculation_engine.renewable_engine import RenewableCalculator
            from simulator.models import LandUse
            
            calculator = RenewableCalculator()
            
            # Load all data sources with fresh values
            landuse_data = {
                i.code: {'status_ha': i.status_ha or 0, 'target_ha': i.target_ha or 0}
                for i in LandUse.objects.all()
            }
            verbrauch_data = {
                i.code: {'status': i.status or 0, 'ziel': i.ziel or 0}
                for i in VerbrauchData.objects.all()
            }
            renewable_data = {
                i.code: {'status_value': i.status_value or 0, 'target_value': i.target_value or 0}
                for i in RenewableData.objects.all()
            }
            
            calculator.set_data_sources(landuse_data, verbrauch_data, renewable_data)
            
            # Recalculate each dependent item
            updated_count = 0
            for item in items_to_update:
                try:
                    calc_status, calc_target = calculator.calculate(item.code)
                    
                    if calc_status is not None and calc_target is not None:
                        status_changed = abs((item.status_value or 0) - calc_status) > 0.01
                        target_changed = abs((item.target_value or 0) - calc_target) > 0.01
                        
                        if status_changed or target_changed:
                            item.status_value = calc_status
                            item.target_value = calc_target
                            item.save(skip_cascade=False)  # Trigger further cascades
                            updated_count += 1
                
                except Exception as e:
                    print(f"❌ Error recalculating RenewableData {item.code} from VerbrauchData {self.code}: {str(e)}")
            
            if updated_count > 0:
                print(f"✅ VerbrauchData {self.code} → {updated_count} RenewableData item(s) recalculated")
        
        except Exception as e:
            print(f"❌ Error in VerbrauchData._recalculate_renewable_dependents for {self.code}: {str(e)}")
    
    def get_hierarchy_level(self):
        """Calculate hierarchy level based on code (1=0, 1.1=1, 1.1.1=2, etc.)"""
        return self.code.count('.')
    
    def get_parent_code(self):
        """Get parent code (1.1.1 -> 1.1, 1.1 -> 1)"""
        if '.' in self.code:
            return '.'.join(self.code.split('.')[:-1])
        return None
    
    def get_effective_value(self):
        """Return the most relevant STATUS value: user_percent > calculated > status"""
        if self.user_percent is not None:
            return self.user_percent
        elif self.status_calculated or self.is_calculated:
            calculated = self.calculate_value()
            if calculated is not None:
                return calculated
        # Return status (not ziel) - this is for status calculations
        return self.status
    
    def get_effective_ziel_value(self):
        """Return the most relevant ziel value: user_percent > calculated_ziel > ziel"""
        if self.user_percent is not None:
            return self.user_percent
        elif self.ziel_calculated or self.is_calculated:
            calculated = self.calculate_ziel_value()
            if calculated is not None:
                return calculated
        return self.ziel
    
    # =============================================================================
    # VERBRAUCH CALCULATION SOURCE: simulator/verbrauch_calculations.py
    # =============================================================================
    # ALL VerbrauchData calculations MUST use this file (170 formulas, 2,589 lines)
    # DO NOT use verbrauch_formulas.py or calculate_verbrauch_values.py
    # This is the ONLY authoritative calculation engine for VerbrauchData
    # =============================================================================
    from .verbrauch_calculations import calculate_value_method, calculate_ziel_value_method
    calculate_value = calculate_value_method
    calculate_ziel_value = calculate_ziel_value_method


class GebaeudewaermeData(models.Model):
    """
    Building Heat Data (Gebäudewärme) Model
    Based on Gebaudewarme_fixed_values.csv structure
    Handles building heating categories and subcategories with hierarchical codes
    """
    # Hierarchical identification
    code = models.CharField(max_length=20, unique=True)  # e.g. "2.0", "2.1", "2.1.1", etc.
    category = models.CharField(max_length=200)  # Building heat category description
    
    # Data values
    unit = models.CharField(max_length=30)  # GWh/a, %, qm/Person, kWh/qm/a, etc.
    status = models.FloatField(null=True, blank=True)  # Current status value
    ziel = models.FloatField(null=True, blank=True)  # Target value (Ziel)
    formula = models.CharField(max_length=100, null=True, blank=True)  # Formula description
    
    # Calculation control
    is_calculated = models.BooleanField(default=False)  # True if this should be calculated via formula
    status_calculated = models.BooleanField(default=False)  # True if STATUS should be calculated
    ziel_calculated = models.BooleanField(default=False)  # True if ZIEL should be calculated
    
    # User interaction (for future functionality)
    user_percent = models.FloatField(null=True, blank=True)  # User-defined percentage
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['code']
        indexes = [
            models.Index(fields=['code']),
        ]
    
    def __str__(self):
        return f"{self.code} - {self.category}"
    
    def get_hierarchy_level(self):
        """Calculate hierarchy level based on code (2=0, 2.1=1, 2.1.1=2, etc.)"""
        return self.code.count('.')
    
    def get_parent_code(self):
        """Get parent code (2.1.1 -> 2.1, 2.1 -> 2.0)"""
        if '.' in self.code:
            return '.'.join(self.code.split('.')[:-1])
        return None
    
    def get_effective_value(self):
        """Return the most relevant value: user_percent > calculated > ziel > status"""
        if self.user_percent is not None:
            return self.user_percent
        elif self.is_calculated:
            return self.calculate_value()
        elif self.ziel is not None:
            return self.ziel
        return self.status
    
    def get_effective_ziel_value(self):
        """Return the most relevant ziel value: user_percent > calculated_ziel > ziel"""
        if self.user_percent is not None:
            return self.user_percent
        elif self.is_calculated:
            return self.calculate_ziel_value()
        return self.ziel
    
    def calculate_value(self, lookup: Optional[dict] = None):
        """
        Placeholder: no calculations currently wired for GebaeudewaermeData.
        """
        return None
    
    def calculate_ziel_value(self, lookup: Optional[dict] = None):
        """
        Placeholder: no calculations currently wired for GebaeudewaermeData.
        """
        return None


class CalculationRun(models.Model):
    """
    Snapshot of an explicit full recalculation (renewable + Verbrauch + WS).
    Stored to let pages read the latest run metadata without re-running heavy steps.
    """
    created_at = models.DateTimeField(auto_now_add=True)
    duration_ms = models.PositiveIntegerField()
    summary = models.JSONField(default=dict, blank=True)
    triggered_by = models.CharField(max_length=150, blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Run at {self.created_at.isoformat()} ({self.duration_ms} ms)"
