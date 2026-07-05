from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

# (app_label, codename) pairs. Kept as an explicit allowlist -- unlike Super
# Admin (which always gets *every* permission that exists), Data Inserter's
# capabilities are deliberately curated and must be extended by hand as new
# permissions become relevant (e.g. `ingestion.add_uploadbatch` once that
# model exists in Day 4).
DATA_INSERTER_PERMISSIONS = [
    ("masterdata", "view_dimbrand"),
    ("masterdata", "view_dimstore"),
    ("masterdata", "view_dimproduct"),
    ("masterdata", "view_branduploadconfig"),
    ("ingestion", "add_uploadbatch"),
    ("ingestion", "view_uploadbatch"),
]


class Command(BaseCommand):
    help = (
        "Seed the Super Admin (all permissions) and Data Inserter (curated "
        "view/upload permissions) groups. Idempotent -- safe to re-run after "
        "new models/permissions are added."
    )

    def handle(self, *args, **options):
        super_admin, _ = Group.objects.get_or_create(name="Super Admin")
        all_permissions = Permission.objects.all()
        super_admin.permissions.set(all_permissions)
        self.stdout.write(f"Super Admin: {all_permissions.count()} permissions")

        data_inserter, _ = Group.objects.get_or_create(name="Data Inserter")
        perms = []
        for app_label, codename in DATA_INSERTER_PERMISSIONS:
            try:
                perms.append(
                    Permission.objects.get(content_type__app_label=app_label, codename=codename)
                )
            except Permission.DoesNotExist:
                self.stderr.write(f"Missing permission {app_label}.{codename}, skipping")
        data_inserter.permissions.set(perms)
        self.stdout.write(f"Data Inserter: {len(perms)} permissions")
