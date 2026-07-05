from rest_framework.permissions import DjangoModelPermissions


class DjangoModelPermissionsIncludingView(DjangoModelPermissions):
    """DjangoModelPermissions doesn't gate GET by default. We want "view" to
    be a real, separately-grantable capability (Data Inserter has it, per
    the frozen "upload + view" role description), not just "authenticated".
    """

    perms_map = {
        **DjangoModelPermissions.perms_map,
        "GET": ["%(app_label)s.view_%(model_name)s"],
        "OPTIONS": ["%(app_label)s.view_%(model_name)s"],
        "HEAD": ["%(app_label)s.view_%(model_name)s"],
    }
