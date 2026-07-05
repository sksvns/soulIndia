from django.apps import AppConfig


class IngestionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ingestion"

    def ready(self):
        from django.db.models.signals import post_save

        from apps.masterdata.models import DimBrand

        from . import signals

        post_save.connect(signals.create_partition_for_new_brand, sender=DimBrand)
