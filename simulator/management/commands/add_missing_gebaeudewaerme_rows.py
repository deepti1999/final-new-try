from django.core.management.base import BaseCommand
from simulator.models import VerbrauchData

class Command(BaseCommand):
    help = 'Add missing calculated rows for Gebäudewärme section'

    def handle(self, *args, **options):
        # Missing calculated rows based on the correct table structure
        missing_rows = [
            # After 2.1 (davon Haushalte) - calculated result
            {
                'code': '2.1.3',
                'category': '= (Result: Haushalte)',
                'unit': 'GWh/a',
                'status': 572.316,
                'ziel': 572.316,
                'is_calculated': True
            },
            # After 2.1.2 (Zieleinfluss Wohnflächen-Entwicklung) - calculated result
            {
                'code': '2.1.2.1',
                'category': '= (Result: nach Wohnflächen-Entwicklung)',
                'unit': 'GWh/a',
                'status': 572.316,
                'ziel': 572.316,
                'is_calculated': True
            },
            # After 2.2 (davon Gewerbe...) - calculated result
            {
                'code': '2.2.2',
                'category': '= (Result: Gewerbe/Handel/Dienstl.)',
                'unit': 'GWh/a',
                'status': 226.551,
                'ziel': 226.551,
                'is_calculated': True
            },
            # After 2.2.1 (Zieleinfluss Erwerbstätigkeit) - calculated result
            {
                'code': '2.2.1.1',
                'category': '= (Result: nach Erwerbstätigkeit)',
                'unit': 'GWh/a',
                'status': 226.551,
                'ziel': 226.551,
                'is_calculated': True
            },
            # After 2.4 (davon Raumwärme) - calculated result
            {
                'code': '2.4.0',
                'category': '= (Result: Raumwärme)',
                'unit': 'GWh/a',
                'status': 686.460,
                'ziel': 686.460,
                'is_calculated': True
            },
            # After 2.4.6 (Result. spez. Raumwärmebed. ges.) - calculated result
            {
                'code': '2.4.7',
                'category': '= Raumwärmebedarf Veränderung',
                'unit': '% v. Status',
                'status': 0.0,
                'ziel': -14.8,
                'is_calculated': True
            },
            {
                'code': '2.4.8',
                'category': '= Bedarfsniveau (Sanierung/Ersatz)',
                'unit': 'GWh/a',
                'status': 686.460,
                'ziel': 584.853,
                'is_calculated': True
            },
            # After 2.5 (davon Warmwasser) - calculated result
            {
                'code': '2.5.0',
                'category': '= (Result: Warmwasser)',
                'unit': 'GWh/a',
                'status': 112.408,
                'ziel': 112.408,
                'is_calculated': True
            },
            # After 2.5.1 (Zieleinfluss Anwendungs-/Prozess-Effizienz) - calculated result
            {
                'code': '2.5.1.1',
                'category': '= (Result: nach Anwendungseffizienz)',
                'unit': 'GWh/a',
                'status': 112.408,
                'ziel': 78.685,
                'is_calculated': True
            },
            # After 2.7 (davon Brennstoffe) - calculated result
            {
                'code': '2.7.0',
                'category': '= Endenergieverbrauch (Brennstoffe)',
                'unit': 'GWh/a',
                'status': 632.410,
                'ziel': 0.0,
                'is_calculated': True
            },
            # Missing absolute value for Einsparung
            {
                'code': '2.7.3.1',
                'category': '= Einsparung gegenüber Status (absolut)',
                'unit': 'GWh/a',
                'status': 0.0,
                'ziel': 0.0,
                'is_calculated': True
            },
            # After 2.8 (davon Wärme) - calculated result
            {
                'code': '2.8.1',
                'category': '= Endenergieverbrauch (Wärme)',
                'unit': 'GWh/a',
                'status': 133.580,
                'ziel': 527.518,
                'is_calculated': True
            },
            # After 2.9 (davon Strom) - calculated result
            {
                'code': '2.9.0',
                'category': '= Endenergieverbrauch (Strom)',
                'unit': 'GWh/a',
                'status': 32.877,
                'ziel': 136.021,
                'is_calculated': True
            },
            # After 2.9.1 (davon für Wärmepumpen) - calculated result
            {
                'code': '2.9.1.1',
                'category': '= Wärmepumpen Endenergieverbrauch',
                'unit': 'GWh/a',
                'status': 10.108,
                'ziel': 136.021,
                'is_calculated': True
            },
        ]
        
        added_count = 0
        
        for row_data in missing_rows:
            # Check if this code already exists
            if not VerbrauchData.objects.filter(code=row_data['code']).exists():
                VerbrauchData.objects.create(**row_data)
                added_count += 1
                self.stdout.write(f'✅ Added {row_data["code"]}: {row_data["category"]}')
            else:
                self.stdout.write(f'⚠️  Skipped {row_data["code"]}: already exists')
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully added {added_count} missing calculated rows')
        )