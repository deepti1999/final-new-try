from django.core.management.base import BaseCommand
from simulator.models import GebaeudewaermeData, VerbrauchData

class Command(BaseCommand):
    help = 'Migrate Gebäudewärme data to Verbrauch model'

    def handle(self, *args, **options):
        # Get all Gebäudewärme data
        gebaeudewaerme_items = GebaeudewaermeData.objects.all()
        
        migrated_count = 0
        
        for item in gebaeudewaerme_items:
            # Check if this code already exists in VerbrauchData
            if not VerbrauchData.objects.filter(code=item.code).exists():
                # Create new VerbrauchData record with compatible fields only
                VerbrauchData.objects.create(
                    code=item.code,
                    category=item.category,
                    unit=item.unit,
                    status=item.status,
                    ziel=item.ziel,
                    is_calculated=item.is_calculated,
                    user_percent=item.user_percent
                )
                migrated_count += 1
                self.stdout.write(f'✅ Migrated {item.code}: {item.category}')
            else:
                self.stdout.write(f'⚠️  Skipped {item.code}: already exists in VerbrauchData')
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully migrated {migrated_count} Gebäudewärme records to VerbrauchData')
        )