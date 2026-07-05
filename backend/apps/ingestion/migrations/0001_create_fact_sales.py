"""Creates the partitioned fact_sales table.

Hand-written (not autodetected): Django's schema editor has no concept of
PostgreSQL declarative partitioning, and its migration autodetector silently
drops ForeignKey fields when generating CreateModel for an unmanaged model.
SeparateDatabaseAndState keeps Django's ORM state (used for query building)
in sync with the model while the real DDL -- CREATE TABLE ... PARTITION BY
LIST, plus every index from plan.md Sec 3 -- runs as plain SQL.
"""

import django.db.models.deletion
from django.db import migrations, models

CREATE_FACT_SALES_SQL = """
CREATE TABLE fact_sales (
    sale_id BIGSERIAL,
    brand_id BIGINT NOT NULL REFERENCES dim_brand(brand_id),
    store_id BIGINT NOT NULL REFERENCES dim_store(store_id),
    product_id BIGINT NOT NULL REFERENCES dim_product(product_id),
    date_id BIGINT NOT NULL REFERENCES dim_calendar(date_id),
    sale_date DATE NOT NULL,
    season_id BIGINT NULL REFERENCES dim_season(season_id),
    invoice_no VARCHAR(64) NOT NULL,
    quantity INTEGER NOT NULL,
    unit_mrp NUMERIC(12, 2) NOT NULL,
    mrp_value NUMERIC(14, 2) NOT NULL,
    net_value NUMERIC(14, 2) NOT NULL,
    discount_value NUMERIC(14, 2) NOT NULL,
    is_return BOOLEAN NOT NULL DEFAULT FALSE,
    extra JSONB NOT NULL DEFAULT '{}'::jsonb,
    upload_batch_id BIGINT NULL,
    source_row_no INTEGER NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (brand_id, sale_date, sale_id)
) PARTITION BY LIST (brand_id);

CREATE INDEX fact_sales_store_invoice_product_idx ON fact_sales (store_id, invoice_no, product_id);
CREATE INDEX fact_sales_store_id_idx ON fact_sales (store_id);
CREATE INDEX fact_sales_product_id_idx ON fact_sales (product_id);
CREATE INDEX fact_sales_date_id_idx ON fact_sales (date_id);
CREATE INDEX fact_sales_season_id_idx ON fact_sales (season_id);
CREATE INDEX fact_sales_upload_batch_id_idx ON fact_sales (upload_batch_id);
CREATE INDEX fact_sales_sale_date_brin_idx ON fact_sales USING BRIN (sale_date);
"""

DROP_FACT_SALES_SQL = "DROP TABLE IF EXISTS fact_sales CASCADE;"


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("masterdata", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="FactSales",
                    fields=[
                        ("sale_id", models.BigAutoField(primary_key=True, serialize=False)),
                        ("sale_date", models.DateField()),
                        ("invoice_no", models.CharField(max_length=64)),
                        ("quantity", models.IntegerField()),
                        ("unit_mrp", models.DecimalField(decimal_places=2, max_digits=12)),
                        ("mrp_value", models.DecimalField(decimal_places=2, max_digits=14)),
                        ("net_value", models.DecimalField(decimal_places=2, max_digits=14)),
                        ("discount_value", models.DecimalField(decimal_places=2, max_digits=14)),
                        ("is_return", models.BooleanField(default=False)),
                        ("extra", models.JSONField(blank=True, default=dict)),
                        ("upload_batch_id", models.BigIntegerField(blank=True, null=True)),
                        ("source_row_no", models.IntegerField(blank=True, null=True)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        (
                            "brand",
                            models.ForeignKey(
                                db_column="brand_id",
                                on_delete=django.db.models.deletion.DO_NOTHING,
                                to="masterdata.dimbrand",
                            ),
                        ),
                        (
                            "store",
                            models.ForeignKey(
                                db_column="store_id",
                                on_delete=django.db.models.deletion.DO_NOTHING,
                                to="masterdata.dimstore",
                            ),
                        ),
                        (
                            "product",
                            models.ForeignKey(
                                db_column="product_id",
                                on_delete=django.db.models.deletion.DO_NOTHING,
                                to="masterdata.dimproduct",
                            ),
                        ),
                        (
                            "date",
                            models.ForeignKey(
                                db_column="date_id",
                                on_delete=django.db.models.deletion.DO_NOTHING,
                                to="masterdata.dimcalendar",
                            ),
                        ),
                        (
                            "season",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                db_column="season_id",
                                on_delete=django.db.models.deletion.DO_NOTHING,
                                to="masterdata.dimseason",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "fact_sales",
                        "managed": False,
                    },
                ),
            ],
            database_operations=[],
        ),
        migrations.RunSQL(sql=CREATE_FACT_SALES_SQL, reverse_sql=DROP_FACT_SALES_SQL),
    ]
