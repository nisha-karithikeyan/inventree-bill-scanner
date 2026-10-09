"""Django app configuration for the bill scanner plugin."""

from django.apps import AppConfig


class BillScannerConfig(AppConfig):
    """App config, registered by InvenTree's AppMixin."""

    name = 'bill_scanner'
    label = 'bill_scanner'
    verbose_name = 'Bill Scanner'
    default_auto_field = 'django.db.models.AutoField'
