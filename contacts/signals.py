from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Contact


@receiver(post_save, sender=Contact)
def enqueue_contact_reminders(sender, instance, **kwargs):
    from .tasks import send_contact_reminders

    transaction.on_commit(
        lambda contact_id=instance.pk: send_contact_reminders.delay(contact_id),
        robust=True,
    )