"""
Import WS (Wärmespeicher/Energy Storage) formulas into Formula database.
"""

from django.core.management.base import BaseCommand
from simulator.models import Formula
from django.db import transaction


class Command(BaseCommand):
    help = 'Import WS (Energy Storage) formulas into Formula database'
    
    def handle(self, *args, **options):
        ws_formulas = [
            # Reference Values (Row 366 baseline)
            {'key': 'WS_REF_PV', 'description': 'PV generation total', 'expression': 'Renewable_1.1.2.1.2 + Renewable_1.2.1.2', 'category': 'ws'},
            {'key': 'WS_REF_WIND', 'description': 'Wind generation total', 'expression': 'Renewable_2.1.1.2.2 + Renewable_2.2.1.2', 'category': 'ws'},
            {'key': 'WS_REF_HYDRO', 'description': 'Hydro generation', 'expression': 'Renewable_3.1.1.2', 'category': 'ws'},
            {'key': 'WS_REF_BIO', 'description': 'Bio energy', 'expression': 'Renewable_4.4.1', 'category': 'ws'},
            {'key': 'WS_REF_ELY', 'description': 'Electrolyzer Power-to-Gas', 'expression': 'Renewable_9.2.1.5.2', 'category': 'ws'},
            {'key': 'WS_REF_N_OUTPUT', 'description': 'N Output Branch', 'expression': 'Renewable_9.3.1', 'category': 'ws'},
            {'key': 'WS_REF_N_INPUT', 'description': 'N Input Branch', 'expression': 'Renewable_9.3.4', 'category': 'ws'},
            {'key': 'WS_REF_TOTAL_GEN', 'description': 'Total renewable generation', 'expression': 'WS_REF_PV + WS_REF_WIND + WS_REF_HYDRO', 'category': 'ws'},
            {'key': 'WS_REF_AFTER_ELY', 'description': 'After electrolyzer', 'expression': 'WS_REF_TOTAL_GEN - WS_REF_ELY', 'category': 'ws'},
            {'key': 'WS_REF_GAS_STORAGE', 'description': 'Gas storage (η=0.65)', 'expression': 'WS_REF_N_OUTPUT * 0.65', 'category': 'ws'},
            {'key': 'WS_REF_T_VALUE', 'description': 'Gas storage offset', 'expression': 'WS_REF_GAS_STORAGE - 160', 'category': 'ws'},
            {'key': 'WS_REF_STROMVERBR_366', 'description': 'Row 366 consumption', 'expression': '(WS_REF_T_VALUE * 0.585) + (WS_REF_TOTAL_GEN - WS_REF_ELY - WS_REF_N_INPUT - WS_REF_N_OUTPUT) + WS_REF_BIO', 'category': 'ws'},
            {'key': 'WS_REF_DAVON_366', 'description': 'Row 366 heating correction', 'expression': 'Verbrauch_2.9.2 * (Verbrauch_2.4 / 100)', 'category': 'ws'},
            {'key': 'WS_REF_SOLAR_366', 'description': 'Solar distribution', 'expression': 'WS_REF_PV * (WS_REF_AFTER_ELY / WS_REF_TOTAL_GEN)', 'category': 'ws'},
            {'key': 'WS_REF_WIND_366', 'description': 'Wind distribution', 'expression': 'WS_REF_WIND * (WS_REF_AFTER_ELY / WS_REF_TOTAL_GEN)', 'category': 'ws'},
            {'key': 'WS_REF_HYDRO_366', 'description': 'Hydro distribution', 'expression': 'WS_REF_HYDRO * (WS_REF_AFTER_ELY / WS_REF_TOTAL_GEN)', 'category': 'ws'},
            
            # Daily Row Calculations
            {'key': 'WS_STROMVERBR', 'description': 'Daily consumption (Col G)', 'expression': 'WS_REF_STROMVERBR_366 * verbrauch_promille / 1000', 'category': 'ws'},
            {'key': 'WS_DAVON_RAUMW_KORR', 'description': 'Daily heating (Col H)', 'expression': 'WS_REF_DAVON_366 * heizung_abwaerm_promille / 365', 'category': 'ws'},
            {'key': 'WS_STROMVERBR_RAUMWAERM_KORR', 'description': 'Consumption + heating (Col J)', 'expression': 'WS_STROMVERBR + WS_DAVON_RAUMW_KORR', 'category': 'ws'},
            {'key': 'WS_WINDSTROM', 'description': 'Daily wind (Col K)', 'expression': 'wind_promille * WS_REF_WIND_366 / 1000', 'category': 'ws'},
            {'key': 'WS_SOLARSTROM', 'description': 'Daily solar (Col L)', 'expression': 'solar_promille * WS_REF_SOLAR_366 / 1000', 'category': 'ws'},
            {'key': 'WS_SONST_KRAFT_KONSTANT', 'description': 'Daily hydro (Col M)', 'expression': 'WS_REF_HYDRO_366 / 365', 'category': 'ws'},
            {'key': 'WS_WIND_SOLAR_KONSTANT', 'description': 'Total generation (Col N)', 'expression': 'WS_WINDSTROM + WS_SOLARSTROM + WS_SONST_KRAFT_KONSTANT', 'category': 'ws'},
            {'key': 'WS_DIREKTVERBR_STROM', 'description': 'Direct consumption (Col O)', 'expression': 'min(WS_WIND_SOLAR_KONSTANT, WS_STROMVERBR_RAUMWAERM_KORR)', 'category': 'ws'},
            {'key': 'WS_UEBERSCHUSS_STROM', 'description': 'Surplus (Col P)', 'expression': 'max(0, WS_WIND_SOLAR_KONSTANT - WS_STROMVERBR_RAUMWAERM_KORR)', 'category': 'ws'},
            {'key': 'WS_EINSPEICH', 'description': 'Storage charge (Col Q)', 'expression': 'min(WS_UEBERSCHUSS_STROM, WS_STROMVERBR_RAUMWAERM_KORR * 1.0) * 0.65', 'category': 'ws', 'notes': 'η=0.65'},
            {'key': 'WS_ABREGELUNG_Z', 'description': 'Curtailment (Col R)', 'expression': 'max(0, WS_UEBERSCHUSS_STROM - (WS_EINSPEICH / 0.65))', 'category': 'ws'},
            {'key': 'WS_MANGEL_LAST', 'description': 'Deficit (Col S)', 'expression': 'WS_STROMVERBR_RAUMWAERM_KORR - WS_DIREKTVERBR_STROM', 'category': 'ws'},
            {'key': 'WS_BRENNSTOFF_AUSGLEICHS_STROM', 'description': 'Bio compensation (Col T)', 'expression': '(WS_REF_BIO / sum_mangel_last_366) * WS_MANGEL_LAST', 'category': 'ws'},
            {'key': 'WS_SPEICHER_AUSGL_STROM', 'description': 'Storage compensation (Col U)', 'expression': 'WS_MANGEL_LAST - WS_BRENNSTOFF_AUSGLEICHS_STROM', 'category': 'ws'},
            {'key': 'WS_AUSSPEICH_RUECKVERSTR', 'description': 'Discharge re-electrification (Col V)', 'expression': 'WS_SPEICHER_AUSGL_STROM / 0.585', 'category': 'ws', 'notes': 'η=0.585'},
            {'key': 'WS_AUSSPEICH_GAS', 'description': 'Gas discharge (Col W)', 'expression': '0', 'category': 'ws'},
            {'key': 'WS_LADEZUST_BURTTO', 'description': 'Gross storage (Col X)', 'expression': 'WS_LADEZUST_BURTTO_PREV + WS_EINSPEICH - WS_AUSSPEICH_RUECKVERSTR - WS_AUSSPEICH_GAS', 'category': 'ws', 'notes': 'Cumulative'},
            {'key': 'WS_LADEZUSTAND_ABS_VORL_TL', 'description': 'Abs storage prelim (Col Y)', 'expression': 'WS_LADEZUST_BURTTO - WS_LADEZUST_BURTTO_367', 'category': 'ws'},
            {'key': 'WS_SELBSTENTL', 'description': 'Self-discharge (Col Z)', 'expression': 'WS_LADEZUSTAND_ABS_VORL_TL * 0', 'category': 'ws'},
            {'key': 'WS_LADEZUSTAND_NETTO', 'description': 'Net storage (Col AA)', 'expression': 'WS_LADEZUSTAND_NETTO_PREV + WS_EINSPEICH - WS_AUSSPEICH_RUECKVERSTR - WS_AUSSPEICH_GAS - WS_SELBSTENTL', 'category': 'ws', 'notes': 'Cumulative'},
            {'key': 'WS_LADEZUSTAND_ABS', 'description': 'Abs storage (Col AB)', 'expression': 'WS_LADEZUSTAND_NETTO - WS_LADEZUSTAND_NETTO_367', 'category': 'ws'},
        ]
        
        self.stdout.write(self.style.MIGRATE_HEADING('Starting WS formula import...'))
        
        created_count = 0
        updated_count = 0
        error_count = 0
        
        with transaction.atomic():
            for formula_data in ws_formulas:
                try:
                    formula, created = Formula.objects.update_or_create(
                        key=formula_data['key'],
                        defaults={
                            'description': formula_data['description'],
                            'expression': formula_data['expression'],
                            'category': formula_data['category'],
                            'notes': formula_data.get('notes', ''),
                        }
                    )
                    
                    if created:
                        created_count += 1
                        self.stdout.write(self.style.SUCCESS(f'  ✓ Created: {formula.key}'))
                    else:
                        updated_count += 1
                        self.stdout.write(self.style.WARNING(f'  ↻ Updated: {formula.key}'))
                        
                except Exception as e:
                    error_count += 1
                    self.stdout.write(self.style.ERROR(f'  ✗ Error with {formula_data["key"]}: {str(e)}'))
        
        # Summary
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Import Summary:'))
        self.stdout.write(f'  Created: {created_count}')
        self.stdout.write(f'  Updated: {updated_count}')
        self.stdout.write(f'  Errors:  {error_count}')
        self.stdout.write(f'  Total:   {len(ws_formulas)}')
        
        if error_count == 0:
            self.stdout.write(self.style.SUCCESS('\n✓ All WS formulas imported successfully!'))
        else:
            self.stdout.write(self.style.ERROR(f'\n✗ {error_count} formulas had errors'))
