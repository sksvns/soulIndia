"""Adds the real FK constraint from fact_sales.upload_batch_id ->
upload_batch.batch_id, deferred from 0001 because upload_batch didn't exist
until 0002 (which itself needed the Day 3 custom User model to exist first).
Hand-written for the same reason as 0001: autodetection cannot be trusted
for fields on an unmanaged model.
"""

import django.db.models.deletion
from django.db import migrations, models

ADD_FK_SQL = """
ALTER TABLE fact_sales
    ADD CONSTRAINT fact_sales_upload_batch_id_fkey
    FOREIGN KEY (upload_batch_id) REFERENCES upload_batch(batch_id);
"""

DROP_FK_SQL = "ALTER TABLE fact_sales DROP CONSTRAINT IF EXISTS fact_sales_upload_batch_id_fkey;"


class Migration(migrations.Migration):
    dependencies = [
        ("ingestion", "0002_uploadbatch"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name="factsales", name="upload_batch_id"),
                migrations.AddField(
                    model_name="factsales",
                    name="batch",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        db_column="upload_batch_id",
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="fact_rows",
                        to="ingestion.uploadbatch",
                    ),
                ),
            ],
            database_operations=[],
        ),
        migrations.RunSQL(sql=ADD_FK_SQL, reverse_sql=DROP_FK_SQL),
    ]
