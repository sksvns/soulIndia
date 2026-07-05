from .partitioning import ensure_brand_partition


def create_partition_for_new_brand(sender, instance, created, **kwargs):
    if created:
        ensure_brand_partition(instance.brand_id)
