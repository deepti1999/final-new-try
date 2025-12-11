"""
Management Command: Add Missing Verbrauch Formulas to Database
=============================================================

This command adds 49 missing Verbrauch formulas that exist in verbrauch_calculations.py
but were not included in the initial import.

USAGE:
    python manage.py add_missing_verbrauch_formulas
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from simulator.models import Formula


class Command(BaseCommand):
    help = 'Add 49 missing Verbrauch formulas to database'

    def handle(self, *args, **options):
        """Add missing formulas"""
        
        # Missing formulas extracted from verbrauch_calculations.py
        MISSING_FORMULAS = {
            'V_2.1.2': {
                'formula': '100',  # Placeholder - status returns 100
                'description': 'Zieleinfluss Wohnflächen-Entwicklung',
            },
            'V_2.4.2': {
                'formula': '100',  # Status returns 100 (simplified from complex IF logic)
                'description': 'Veränderung zum Status',
            },
            'V_2.4.5': {
                'formula': '0',  # Status = 0 (no renovation in base year)
                'description': 'Gebäudeanteil mit Ziel-Wärmeschutz (Status)',
            },
            'V_2.4.6': {
                'formula': 'Verbrauch_2.4.1',  # Status = copy of 2.4.1
                'description': 'Resultierender spez. Raumwärmebedarf gesamt',
            },
            'V_2.5.3': {
                'formula': 'Verbrauch_2.5.2 / Verbrauch_2.6 * 100',
                'description': 'Resultierender Anteil Warmwasser an Gebäudewärme',
            },
            'V_2.7.2': {
                'formula': 'Verbrauch_2.7 * (1 - Verbrauch_2.7.1 / 100)',
                'description': 'Wandlungsverluste Endanwendung',
            },
            'V_2.7.3': {
                'formula': '0',  # Always 0 for status
                'description': 'Einsparung gegenüber Status (relativ)',
            },
            'V_2.7.4': {
                'formula': 'Verbrauch_2.6 * Verbrauch_2.7.3 / 100',
                'description': 'Einsparung gegenüber Status (absolut)',
            },
            'V_2.9': {
                'formula': '100 - Verbrauch_2.8 - Verbrauch_2.7 - Verbrauch_2.7.3',
                'description': 'davon Strom (verlustarm nutzbar)',
            },
            'V_2.9.1': {
                'formula': 'Verbrauch_2.9.2 / (Verbrauch_2.9.0 / 100)',
                'description': 'davon für Wärmepumpen',
            },
            'V_3.4.2': {
                'formula': 'Verbrauch_3.4 * (1 - Verbrauch_3.4.1 / 100)',
                'description': 'Wandlungsverluste Endanwendung',
            },
            'V_3.4.3': {
                'formula': '0',  # Always 0
                'description': 'Einsparung gegenüber Status (relativ)',
            },
            'V_3.4.4': {
                'formula': 'Verbrauch_3.4.3 * Verbrauch_3.3 / 100',
                'description': 'Einsparung gegenüber Status (absolut)',
            },
            'V_3.6': {
                'formula': '100 - Verbrauch_3.4 - Verbrauch_3.5 - Verbrauch_3.4.3',
                'description': 'davon Strom (verlustarm nutzbar)',
            },
            'V_4.1.1.3': {
                'formula': 'Verbrauch_4.1.1.6 * Verbrauch_4.1.1.7 / 100 / 100 + Verbrauch_4.1.1.11 * Verbrauch_4.1.1.12 / 100 / 100',
                'description': 'Nutzungsgrad Traktionsmix',
            },
            'V_4.1.1.4.0': {
                'formula': 'Verbrauch_4.1.1.2 * Verbrauch_4.1.1.3 / 100',
                'description': 'Nutzenergie (NE) gesamt PVk',
            },
            'V_4.1.1.4.1': {
                'formula': 'Verbrauch_4.1.1.4.0',  # Ziel only - not calculated for Status
                'description': 'Nutzenergie (NE) gesamt PVk (Ziel)',
            },
            'V_4.1.1.8': {
                'formula': 'Verbrauch_4.1.1.6 * Verbrauch_4.1.1.7 / 100',
                'description': 'Anteil NE Elektrotraktion an Endverbrauch PVk',
            },
            'V_4.1.1.9': {
                'formula': 'Verbrauch_4.1.1.8 / (Verbrauch_4.1.1.3 / 100)',
                'description': 'Anteil NE Elektrotraktion an NE gesamt PVk',
            },
            'V_4.1.1.10': {
                'formula': 'Verbrauch_4.1.1.4.0 * Verbrauch_4.1.1.9 / Verbrauch_4.1.1.7',
                'description': 'Stromverbrauch PVk',
            },
            'V_4.1.1.11': {
                'formula': '100 - Verbrauch_4.1.1.6',  # Simplified - depends on FC mode
                'description': 'Anteil Verbrennungstraktion an Endverbrauch PVk',
            },
            'V_4.1.1.13': {
                'formula': 'Verbrauch_4.1.1.11 * Verbrauch_4.1.1.12 / 100',
                'description': 'Anteil NE Verbrennungstraktion an Endverbrauch PVk',
            },
            'V_4.1.1.14': {
                'formula': '100 - Verbrauch_4.1.1.9',
                'description': 'Anteil NE Verbrennungstraktion an NE gesamt PVk',
            },
            'V_4.1.1.15': {
                'formula': 'Verbrauch_4.1.1.4.0 * Verbrauch_4.1.1.14 / Verbrauch_4.1.1.12',
                'description': 'Kohlenwasserstoffverbrauch (gasförmig) PVk',
            },
            'V_4.1.1.16': {
                'formula': '0',  # Depends on FC mode - simplified
                'description': 'Anteil FC-Traktion an Endverbrauch PVk',
            },
            'V_4.1.1.18': {
                'formula': 'Verbrauch_4.1.1.16 * Verbrauch_4.1.1.17 / 100',
                'description': 'Anteil NE FC-Traktion an Endverbrauch PVk',
            },
            'V_4.1.1.19': {
                'formula': '0',  # Depends on FC mode
                'description': 'Anteil NE FC-Traktion an NE gesamt PVk',
            },
            'V_4.1.1.20': {
                'formula': 'Verbrauch_4.1.1.4.0 * Verbrauch_4.1.1.19 / Verbrauch_4.1.1.17',
                'description': 'Wasserstoffverbrauch PVk',
            },
            'V_4.1.2': {
                'formula': '100 - Verbrauch_4.1.1',
                'description': 'davon Güterverkehr u.a. (GVk)',
            },
            'V_4.1.2.3': {
                'formula': 'Verbrauch_4.1.2.6 * Verbrauch_4.1.2.7 / 100 + Verbrauch_4.1.2.11 * Verbrauch_4.1.2.12 / 100',
                'description': 'Nutzungsgrad Traktionsmix GVk',
            },
            'V_4.1.2.4.0': {
                'formula': 'Verbrauch_4.1.2.2 * Verbrauch_4.1.2.3 / 100',
                'description': 'Nutzenergie (NE) gesamt GVk',
            },
            'V_4.1.2.4.1': {
                'formula': 'Verbrauch_4.1.2.4.0',  # Ziel calculation different
                'description': 'Nutzenergie (NE) gesamt GVk (Ziel)',
            },
            'V_4.1.2.8': {
                'formula': 'Verbrauch_4.1.2.6 * Verbrauch_4.1.2.7 / 100',
                'description': 'Anteil NE Elektrotraktion an Endverbrauch GVk',
            },
            'V_4.1.2.9': {
                'formula': 'Verbrauch_4.1.2.8 / Verbrauch_4.1.2.3 * 100',
                'description': 'Anteil NE Elektrotraktion an NE gesamt GVk',
            },
            'V_4.1.2.10': {
                'formula': 'Verbrauch_4.1.2.4.0 * Verbrauch_4.1.2.9 / Verbrauch_4.1.2.7',
                'description': 'Stromverbrauch GVk',
            },
            'V_4.1.2.11': {
                'formula': '100 - Verbrauch_4.1.2.6',
                'description': 'Anteil Verbrennungstraktion an Endverbrauch GVk',
            },
            'V_4.1.2.13': {
                'formula': 'Verbrauch_4.1.2.11 * Verbrauch_4.1.2.12 / 100',
                'description': 'Anteil NE Verbrennungstraktion an Endverbrauch GVk',
            },
            'V_4.1.2.14': {
                'formula': '100 - Verbrauch_4.1.2.9',
                'description': 'Anteil NE Verbrennungstraktion an NE gesamt GVk',
            },
            'V_4.1.2.15': {
                'formula': 'Verbrauch_4.1.2.4.0 * Verbrauch_4.1.2.14 / Verbrauch_4.1.2.12',
                'description': 'Kohlenwasserstoffverbrauch (gasförmig) GVk',
            },
            'V_4.1.2.16': {
                'formula': '0',  # Depends on FC mode
                'description': 'Anteil FC-Traktion an Endverbrauch GVk',
            },
            'V_4.1.2.18': {
                'formula': 'Verbrauch_4.1.2.16 * Verbrauch_4.1.2.17 / 100',
                'description': 'Anteil NE FC-Traktion an Endverbrauch GVk',
            },
            'V_4.1.2.19': {
                'formula': '0',  # Depends on FC mode
                'description': 'Anteil NE FC-Traktion an NE gesamt GVk',
            },
            'V_4.1.2.20': {
                'formula': 'Verbrauch_4.1.2.4.0 * Verbrauch_4.1.2.19 / Verbrauch_4.1.2.17',
                'description': 'Wasserstoffverbrauch GVk',
            },
            'V_4.3.2': {
                'formula': 'Verbrauch_4.1.1.15 + Verbrauch_4.1.2.15 + Verbrauch_4.2.5',
                'description': 'davon Kraftstoffe',
            },
            'V_4.3.3': {
                'formula': 'Verbrauch_4.1.1.20 + Verbrauch_4.1.2.20',
                'description': 'davon Wasserstoff (FC-Traktion)',
            },
            'V_4.3.4': {
                'formula': 'Verbrauch_4.1.1.15 + Verbrauch_4.1.2.15',
                'description': 'davon Kohlenwasserstoff (gasförmig)',
            },
            'V_4.3.5': {
                'formula': 'Verbrauch_4.2.5',
                'description': 'davon Kohlenwasserstoff (flüssig, für Luftverkehr)',
            },
            'V_4.3.6': {
                'formula': 'Verbrauch_4.1.1.10 + Verbrauch_4.1.2.10',
                'description': 'davon Strom',
            },
            'V_7.1.4': {
                'formula': 'Verbrauch_7.1.2 * Verbrauch_7.1.3 / 100',
                'description': 'Bedarf an synthetischen Grundstoffen',
            },
        }
        
        created_count = 0
        updated_count = 0
        
        with transaction.atomic():
            for key, data in MISSING_FORMULAS.items():
                formula, created = Formula.objects.update_or_create(
                    key=key,
                    defaults={
                        'expression': data['formula'],
                        'description': data['description'],
                        'category': 'verbrauch',
                        'is_active': True,
                        'is_fixed': False,
                        'validation_status': 'pending',
                    }
                )
                
                if created:
                    created_count += 1
                    self.stdout.write(self.style.SUCCESS(f'✓ Created: {key}'))
                else:
                    updated_count += 1
                    self.stdout.write(self.style.WARNING(f'⟳ Updated: {key}'))
        
        self.stdout.write(self.style.SUCCESS(
            f'\n✅ Import Complete!\n'
            f'   Created: {created_count} formulas\n'
            f'   Updated: {updated_count} formulas\n'
            f'   Total: {created_count + updated_count} formulas'
        ))
        
        # Show total count
        total = Formula.objects.filter(category='verbrauch').count()
        self.stdout.write(self.style.SUCCESS(
            f'\n📊 Total Verbrauch formulas in database: {total}'
        ))
