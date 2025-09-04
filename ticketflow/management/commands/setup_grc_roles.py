from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group

GROUPS = ["RR", "RC", "RA", "CRO"]

class Command(BaseCommand):
    help = "Create default GRC role groups"

    def handle(self, *args, **kwargs):
        for name in GROUPS:
            Group.objects.get_or_create(name=name)
        self.stdout.write(self.style.SUCCESS("GRC groups ensured: " + ", ".join(GROUPS)))
