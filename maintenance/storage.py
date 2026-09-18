from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible
from django.utils.functional import cached_property


@deconstructible
class PrivateInvoiceStorage(FileSystemStorage):
    @cached_property
    def base_location(self):
        return Path(settings.PRIVATE_INVOICE_ROOT)

    @cached_property
    def location(self):
        return self.base_location.resolve()

    def url(self, name):
        raise ValueError(
            "Les factures privées ne possèdent pas d'URL publique.")


private_invoice_storage = PrivateInvoiceStorage()
