from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from django.utils.html import format_html
from .models import LandUse, RenewableData, VerbrauchData, WSData

class DataTypeFilter(SimpleListFilter):
    title = 'Data Type'
    parameter_name = 'data_type'
    
    def lookups(self, request, model_admin):
        return (
            ('klik', 'KLIK'),
            ('gebaeudewaerme', 'Gebäudewärme'),
            ('prozesswaerme', 'Prozesswärme'),
            ('mobile_anwendungen', 'Mobile Anwendungen'),
            ('strom_endverbrauch', 'Strom-Endverbrauch'),
            ('endenergieverbrauch', 'Endenergieverbrauch'),
            ('other', 'Other'),
        )
    
    def queryset(self, request, queryset):
        if self.value() == 'klik':
            return queryset.filter(code__startswith='1')
        elif self.value() == 'gebaeudewaerme':
            return queryset.filter(code__startswith='2')
        elif self.value() == 'prozesswaerme':
            return queryset.filter(code__startswith='3')
        elif self.value() == 'mobile_anwendungen':
            return queryset.filter(code__startswith='4')
        elif self.value() == 'strom_endverbrauch':
            return queryset.filter(code='5')
        elif self.value() == 'endenergieverbrauch':
            return queryset.filter(code='6')
        elif self.value() == 'other':
            return queryset.exclude(code__regex=r'^[1-6]')

@admin.register(LandUse)
class LandUseAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'status_ha', 'target_ha', 'parent', 'quelle']
    list_filter = ['quelle', 'parent']
    search_fields = ['code', 'name']
    ordering = ['code']
    
    # Enable editing for actual database fields only
    list_editable = ['status_ha', 'target_ha']
    list_per_page = 25
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('code', 'name', 'parent', 'quelle')
        }),
        ('Data (Editable)', {
            'fields': ('status_ha', 'target_ha'),
            'description': 'Edit hectare values. Percentages and ratios are calculated automatically.'
        }),
    )


@admin.register(RenewableData)
class RenewableDataAdmin(admin.ModelAdmin):
    # Show all entries with values only for fixed items
    list_display = ['code', 'name', 'category', 'subcategory', 'unit', 'status_display', 'target_display', 'is_fixed', 'parent_code']
    list_filter = ['category', 'subcategory', 'is_fixed', 'created_at']
    search_fields = ['code', 'name', 'category', 'subcategory']
    ordering = ['code']
    
    # Enable editing for status and target values in the list for fixed items only
    list_editable = ['is_fixed']
    list_per_page = 100  # Show more entries per page
    
    # Add JavaScript for instant field toggling
    class Media:
        js = ('admin/js/renewable_toggle.js',)
    
    def status_display(self, obj):
        """Show status value only for fixed items (non-formula items)"""
        if obj.is_fixed:
            return obj.status_value if obj.status_value is not None else "-"
        return ""  # Empty for calculated items
    status_display.short_description = 'Status Value'
    
    def target_display(self, obj):
        """Show target value only for fixed items (non-formula items)"""
        if obj.is_fixed:
            return obj.target_value if obj.target_value is not None else "-"
        return ""  # Empty for calculated items
    target_display.short_description = 'Target Value'
    
    fieldsets = (
        ('Identification', {
            'fields': ('code', 'name', 'category', 'subcategory', 'description')
        }),
        ('Hierarchy', {
            'fields': ('parent_code',),
            'description': 'Hierarchical parent relationship.'
        }),
        ('Data Values - Editable for Fixed Items Only', {
            'fields': ('unit', 'status_value', 'target_value', 'user_input'),
            'description': 'Edit values for fixed items. Formula items are calculated automatically.'
        }),
        ('Calculation', {
            'fields': ('is_fixed', 'formula'),
            'description': 'Whether value is fixed or calculated, and formula if applicable.'
        }),
        ('Metadata', {
            'fields': ('source', 'notes'),
            'classes': ('collapse',)
        }),
    )
    
    def get_readonly_fields(self, request, obj=None):
        """Make value fields readonly for calculated items, editable for fixed items"""
        # Always readonly: created_at, updated_at, code
        readonly = ['created_at', 'updated_at', 'code']
        
        # Formula is always readonly (shown for information only)
        readonly.append('formula')
        
        # For new objects, don't restrict anything yet
        if not obj:
            return readonly
            
        # For existing objects with formulas (is_fixed=False), make values readonly
        if not obj.is_fixed:
            readonly.extend(['status_value', 'target_value', 'user_input'])
        
        return readonly
    
    # No longer need these display methods in detail view
    # Remove the old status_value_display, target_value_display, user_input_display methods


@admin.register(VerbrauchData)
class VerbrauchDataAdmin(admin.ModelAdmin):
    list_display = ['code', 'category_display', 'unit', 'status_display', 'ziel_display', 'user_percent_display', 'is_calculated', 'data_type']
    list_filter = [DataTypeFilter, 'is_calculated', 'unit', 'created_at']
    search_fields = ['code', 'category']
    ordering = ['code']
    
    # Enable editing for key fields - only for non-calculated items
    list_editable = ['is_calculated']
    list_per_page = 30
    
    fieldsets = (
        ('Identification', {
            'fields': ('code', 'category')
        }),
        ('Data Values', {
            'fields': ('unit', 'status', 'ziel', 'user_percent'),
            'description': 'Current status, target (Ziel), and user percentage values. Only editable for fixed values.'
        }),
        ('Calculation', {
            'fields': ('is_calculated',),
            'description': 'Whether this value should be calculated via formula.'
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_readonly_fields(self, request, obj=None):
        """Make status/ziel readonly for calculated items"""
        readonly = list(self.readonly_fields)
        if obj and obj.is_calculated:
            readonly.extend(['status', 'ziel', 'user_percent'])
        return readonly
    
    readonly_fields = ['created_at', 'updated_at']
    
    def category_display(self, obj):
        """Truncate long category names for better display and add CSS classes"""
        category_text = obj.category
        if len(category_text) > 50:
            category_text = category_text[:47] + "..."
        
        # Add bold styling for "Strom-Endverbrauch insgesamt"
        if "Strom-Endverbrauch insgesamt" in obj.category:
            return format_html('<span style="font-weight: bold;">{}</span>', category_text)
        
        # Add bold styling for "Endenergieverbrauch insgesamt"
        if "Endenergieverbrauch insgesamt" in obj.category:
            return format_html('<span style="font-weight: bold;">{}</span>', category_text)
        
        # Add green styling for FC-Traktion alternative entries
        if "Alternativ zur" in obj.category and "Brennstoffzellen (FC)" in obj.category:
            return format_html('<span style="color: green; font-style: italic;">{}</span>', category_text)
        
        return category_text
    category_display.short_description = 'Category'
    
    def format_number(self, value):
        """Format number properly: commas for thousands (>=1000), decimals for smaller"""
        if value is None:
            return "-"
        
        # Always check if it's a whole number first
        if value == int(value):
            if value >= 1000:
                return f"{int(value):,}"  # Comma separator, no decimals for whole numbers
            else:
                return f"{int(value):,}"    # No decimals, comma for smaller whole numbers too
        else:
            # For non-whole numbers
            return f"{value:,.4f}".rstrip('0').rstrip('.')  # up to 4 decimals, comma thousands
    
    def status_display(self, obj):
        """Format status value for display - only show for fixed values"""
        # Special list of fixed items that should show values
        fixed_items = ['4.2.1', '4.2.2', '4.2.4']
        
        # 4.3.x series should never show values (all calculated by formulas)
        if obj.code.startswith('4.3.'):
            return ""
        
        # Only show values for fixed items or non-calculated items (legacy)
        if obj.code in fixed_items or not obj.is_calculated:
            # Special case: 2.4.5 status is always stored (0), never calculated
            if obj.code == '2.4.5':
                result = self.format_number(obj.status)
                return f"{result}✓" if result == "0" else result
            # Only show if value exists
            if obj.status is not None:
                return self.format_number(obj.status)
        return ""  # Empty for calculated items or items without values
    status_display.short_description = 'Status'
    
    def ziel_display(self, obj):
        """Format ziel value for display - only show for fixed values"""
        # Special case: FC-Traktion alternative entries show "(Passiv)" in Ziel column
        if "Alternativ zur" in obj.category and "Brennstoffzellen (FC)" in obj.category:
            return "(Passiv)"
        
        # 4.3.x series should never show values (all calculated by formulas)
        if obj.code.startswith('4.3.'):
            return ""
        
        # Special list of fixed items that should show values
        fixed_items = ['4.2.1', '4.2.2', '4.2.4']
        
        # Only show values for fixed items or non-calculated items (legacy)
        if obj.code in fixed_items or not obj.is_calculated:
            # Only show if value exists
            if obj.ziel is not None:
                return self.format_number(obj.ziel)
        return ""  # Empty for calculated items or items without values
    ziel_display.short_description = 'Ziel'
    
    def user_percent_display(self, obj):
        """Format user_percent value for display - only show for fixed values"""
        # 4.3.x series should never show values (all calculated by formulas)
        if obj.code.startswith('4.3.'):
            return ""
        
        # Special list of fixed items that should show values
        fixed_items = ['4.2.1', '4.2.2', '4.2.4']
        
        # Only show values for fixed items or non-calculated items (legacy)
        if obj.code in fixed_items or not obj.is_calculated:
            if obj.user_percent is not None:
                return self.format_number(obj.user_percent)
        return ""  # Empty for calculated items or items without values
    user_percent_display.short_description = 'User %'

    def save_model(self, request, obj, form, change):
        """
        Save with cascades/recalc (default), but keep admin responsive by
        refreshing from DB after save.
        """
        super().save_model(request, obj, form, change)
        obj.refresh_from_db()
    
    def data_type(self, obj):
        """Show whether this is KLIK, Gebäudewärme, Prozesswärme, Mobile Anwendungen, Strom-Endverbrauch, or Endenergieverbrauch data"""
        if obj.code.startswith('1'):
            return "KLIK"
        elif obj.code.startswith('2'):
            return "Gebäudewärme"
        elif obj.code.startswith('3'):
            return "Prozesswärme"
        elif obj.code.startswith('4'):
            return "Mobile Anwendungen"
        elif obj.code == '5':
            return "Strom-Endverbrauch"
        elif obj.code == '6':
            return "Endenergieverbrauch"
        else:
            return "Other"
    data_type.short_description = 'Type'


@admin.register(WSData)
class WSDataAdmin(admin.ModelAdmin):
    """
    Admin interface for WS (Wärmespeicher/Energy Storage) Data
    Displays all columns from the Excel sheet in a structured grid
    ALL FIELDS ARE FULLY EDITABLE
    """
    
    def format_decimal(self, value):
        """Format decimal number in English format: 1,234.567890"""
        if value is None:
            return "-"
        # Format with up to 15 decimal places, remove trailing zeros
        formatted = f"{float(value):,.15f}".rstrip('0').rstrip('.')
        return formatted
    
    # Create display methods for all numeric fields
    def wind_promille_display(self, obj):
        return self.format_decimal(obj.wind_promille)
    wind_promille_display.short_description = 'Wind Promille'
    
    def solar_promille_display(self, obj):
        return self.format_decimal(obj.solar_promille)
    solar_promille_display.short_description = 'Solar Promille'
    
    def heizung_abwaerm_promille_display(self, obj):
        return self.format_decimal(obj.heizung_abwaerm_promille)
    heizung_abwaerm_promille_display.short_description = 'Heizung Abwärm Promille'
    
    def verbrauch_promille_display(self, obj):
        return self.format_decimal(obj.verbrauch_promille)
    verbrauch_promille_display.short_description = 'Verbrauch Promille'
    
    def stromverbr_display(self, obj):
        return self.format_decimal(obj.stromverbr)
    stromverbr_display.short_description = 'Stromverbr'
    
    def davon_raumw_korr_display(self, obj):
        return self.format_decimal(obj.davon_raumw_korr)
    davon_raumw_korr_display.short_description = 'Davon Raumw Korr'
    
    def stromverbr_raumwaerm_korr_display(self, obj):
        return self.format_decimal(obj.stromverbr_raumwaerm_korr)
    stromverbr_raumwaerm_korr_display.short_description = 'Stromverbr Raumwärm Korr'
    
    def windstrom_display(self, obj):
        return self.format_decimal(obj.windstrom)
    windstrom_display.short_description = 'Windstrom'
    
    def solarstrom_display(self, obj):
        return self.format_decimal(obj.solarstrom)
    solarstrom_display.short_description = 'Solarstrom'
    
    def sonst_kraft_konstant_display(self, obj):
        return self.format_decimal(obj.sonst_kraft_konstant)
    sonst_kraft_konstant_display.short_description = 'Sonst Kraft Konstant'
    
    def wind_solar_konstant_display(self, obj):
        return self.format_decimal(obj.wind_solar_konstant)
    wind_solar_konstant_display.short_description = 'Wind+Solar Konstant'
    
    def direktverbr_strom_display(self, obj):
        return self.format_decimal(obj.direktverbr_strom)
    direktverbr_strom_display.short_description = 'Direktverbr Strom'
    
    def ueberschuss_strom_display(self, obj):
        return self.format_decimal(obj.ueberschuss_strom)
    ueberschuss_strom_display.short_description = 'Ueberschuss Strom'
    
    def einspeich_display(self, obj):
        return self.format_decimal(obj.einspeich)
    einspeich_display.short_description = 'Einspeich'
    
    def abregelung_z_display(self, obj):
        return self.format_decimal(obj.abregelung_z)
    abregelung_z_display.short_description = 'Abregelung Z'
    
    def mangel_last_display(self, obj):
        return self.format_decimal(obj.mangel_last)
    mangel_last_display.short_description = 'Mangel Last'
    
    def brennstoff_ausgleichs_strom_display(self, obj):
        return self.format_decimal(obj.brennstoff_ausgleichs_strom)
    brennstoff_ausgleichs_strom_display.short_description = 'Brennstoff Ausgleichs Strom'
    
    def speicher_ausgl_strom_display(self, obj):
        return self.format_decimal(obj.speicher_ausgl_strom)
    speicher_ausgl_strom_display.short_description = 'Speicher Ausgl Strom'
    
    def ausspeich_rueckverstr_display(self, obj):
        return self.format_decimal(obj.ausspeich_rueckverstr)
    ausspeich_rueckverstr_display.short_description = 'Ausspeich Rückverstr'
    
    def ausspeich_gas_display(self, obj):
        return self.format_decimal(obj.ausspeich_gas)
    ausspeich_gas_display.short_description = 'Ausspeich Gas'
    
    def ladezust_burtto_display(self, obj):
        return self.format_decimal(obj.ladezust_burtto)
    ladezust_burtto_display.short_description = 'Ladezust Burtto'
    
    def ladezustand_abs_vorl_tl_display(self, obj):
        return self.format_decimal(obj.ladezustand_abs_vorl_tl)
    ladezustand_abs_vorl_tl_display.short_description = 'Ladezustand Abs Vorl TL'
    
    def selbstentl_display(self, obj):
        return self.format_decimal(obj.selbstentl)
    selbstentl_display.short_description = 'Selbstentl'
    
    def ladezustand_netto_display(self, obj):
        return self.format_decimal(obj.ladezustand_netto)
    ladezustand_netto_display.short_description = 'Ladezustand Netto'
    
    def ladezustand_abs_display(self, obj):
        return self.format_decimal(obj.ladezustand_abs)
    ladezustand_abs_display.short_description = 'Ladezustand Abs.'
    
    list_display = [
        'tag_im_jahr', 'datum_ref', 
        'wind_promille_display', 'solar_promille_display', 'heizung_abwaerm_promille_display', 'verbrauch_promille_display',
        'stromverbr_display', 'davon_raumw_korr_display', 'stromverbr_raumwaerm_korr_display',
        'windstrom_display', 'solarstrom_display', 'sonst_kraft_konstant_display', 'wind_solar_konstant_display',
        'direktverbr_strom_display', 'ueberschuss_strom_display', 'einspeich_display', 'abregelung_z_display',
        'mangel_last_display', 'brennstoff_ausgleichs_strom_display', 'speicher_ausgl_strom_display',
        'ausspeich_rueckverstr_display', 'ausspeich_gas_display', 'ladezust_burtto_display', 'ladezustand_abs_vorl_tl_display', 'selbstentl_display', 'ladezustand_netto_display', 'ladezustand_abs_display'
    ]
    
    list_filter = ['datum_ref']
    search_fields = ['tag_im_jahr', 'datum_ref']
    ordering = ['tag_im_jahr']
    
    # Disable inline editing in list view (use detail form instead for proper number formatting)
    list_editable = []
    
    list_per_page = 50
    
    # All fields organized in logical groups - ALL EDITABLE
    fieldsets = (
        ('Date Information', {
            'fields': ('tag_im_jahr', 'datum_ref'),
            'description': 'Day number and date reference'
        }),
        ('Promille Values (Columns C-F)', {
            'fields': ('wind_promille', 'solar_promille', 'heizung_abwaerm_promille', 'verbrauch_promille'),
            'description': 'Wind, Solar, Heizung, and Verbrauch in Promille'
        }),
        ('Primary Energy Values (Columns G-N)', {
            'fields': (
                'stromverbr',                    # Column G: Stromverbr.
                'davon_raumw_korr',             # Column H: davon Raumw.korr.
                'raumwaerm_korr',               # Column I: Raumwärm.Korr.
                'stromverbr_raumwaerm_korr',    # Column J: Stromverbr. Raumwärm.Korr.
                'windstrom',                     # Column K: Windstrom
                'solarstrom',                    # Column L: Solarstrom
                'sonst_kraft_konstant',          # Column M: Sonst.Kraft(konstant)
                'wind_solar_konstant'            # Column N: Wind+Solar Konstant
            ),
            'description': 'Columns G through N - Primary energy calculations'
        }),
        ('Distribution & Usage (Columns O-S)', {
            'fields': (
                'direktverbr_strom',    # Column O
                'ueberschuss_strom',    # Column P
                'entsteht',             # Column Q
                'abgeltung',            # Column R
                'mangel_last'           # Column S
            ),
            'description': 'Energy distribution and usage parameters'
        }),
        ('Storage & Compensation (Columns Q-AB)', {
            'fields': (
                'einspeich',                     # Column Q
                'abregelung_z',                  # Column R
                'brennstoff_ausgleichs_strom',   # Column T
                'speicher_ausgl_strom',          # Column U
                'ausspeich_rueckverstr',         # Column V
                'ausspeich_gas',                 # Column W
                'ladezust_burtto',               # Column X
                'ladezustand_abs_vorl_tl',       # Column Y
                'selbstentl',                    # Column Z
                'ladezustand_netto',             # Column AA
                'ladezustand_abs',               # Column AB
                'aussprech_rueckwaerts',         # Old Column V
                'aussprech_gas'                  # Old Column W
            ),
            'description': 'Storage and compensation values'
        }),
        ('Load & State Parameters (Columns AB-AD)', {
            'fields': (
                'netto',                    # Column AB
                'ladeabbzustan',            # Column AC
                'abacadae'                  # Column AD
            ),
            'description': 'Load and state parameters'
        }),
        ('Overview Parameters (Columns AF-AH)', {
            'fields': (
                'uebersicht_speich_last',   # Column AF
                'uebersicht_aussprech',     # Column AG
                'uebersicht_entspeich'      # Column AH
            ),
            'description': 'Overview summary values'
        }),
        ('Conversion & Technical Parameters (Columns AI-AP)', {
            'fields': (
                'umrechnun',            # Column AI
                'tl_mwh_1y',           # Column AJ
                'konstanstr_tl',       # Column AK
                'solarstrom_tl',       # Column AL
                'windstrom_tl',        # Column AM
                'solar_konst_tl',      # Column AN
                'konst_win_solar_tl',  # Column AO
                'verbrauch_tl'         # Column AP
            ),
            'description': 'TL (Technical Load) conversion parameters'
        }),
        ('Additional Calculations (Columns AQ-AZ)', {
            'fields': (
                'konstantstr',              # Column AQ
                'solar_kons_1_tageay',     # Column AR
                'wind_sol_win_tv',         # Column AS
                'unterbedeck',             # Column AT
                'solar_tv',                # Column AU
                'wind_tv',                 # Column AV
                'ladeabzustan_d_abs_tl',   # Column AW
                'unterbedeck_ohne_wind',   # Column AX
                'additional_column_ay',    # Column AY
                'additional_column_az'     # Column AZ
            ),
            'description': 'Additional calculation columns'
        }),
    )
    
    # NO readonly fields - everything is editable
    def get_readonly_fields(self, request, obj=None):
        return []
    
    # Enable bulk actions
    actions = ['duplicate_entries']
    
    def duplicate_entries(self, request, queryset):
        """Allow duplicating selected entries for quick data entry"""
        for obj in queryset:
            obj.pk = None
            obj.save()
        self.message_user(request, f"{queryset.count()} entries duplicated successfully.")
    duplicate_entries.short_description = "Duplicate selected entries"
