"""Day 12: bootstraps the very first admin on a fresh production
database, where nobody can use /admin/'s own "add user" screen yet
because nobody can log in. Idempotent -- re-running with the same email
just makes sure that user is in the Super Admin group, rather than
erroring, matching seed_roles' "safe to re-run" convention."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()


class Command(BaseCommand):
    help = "Creates (or promotes) the initial Super Admin user for a fresh deployment."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--password", required=True)

    def handle(self, *args, **options):
        email = options["email"]
        password = options["password"]
        if len(password) < 12:
            raise CommandError("--password must be at least 12 characters")

        call_command("seed_roles", stdout=self.stdout)
        super_admin_group = Group.objects.get(name="Super Admin")

        user, created = User.objects.get_or_create(email=email, defaults={"is_staff": True})
        user.is_staff = True
        user.set_password(password)
        user.save(update_fields=["is_staff", "password"])
        user.groups.add(super_admin_group)

        self.stdout.write(
            self.style.SUCCESS(f"Super Admin {'created' if created else 'updated'}: {email}")
        )
