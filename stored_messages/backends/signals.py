from django.dispatch import Signal

inbox_stored = Signal()
inbox_deleted = Signal()
inbox_purged = Signal()

archive_stored = Signal()
