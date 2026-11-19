"""CONTACT_ADDED trigger: fires when a contact is newly added to a ContactList (any code path)."""
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from contacts.models import Contact

from .triggers import handle_contact_added_to_lists


@receiver(m2m_changed, sender=Contact.lists.through)
def contact_lists_changed(sender, instance, action, reverse, pk_set, **kwargs):
    # post_add's pk_set only contains rows that were NEWLY added, so re-adding an existing
    # member (or a no-op .set()) does not re-fire the trigger.
    if action != "post_add" or not pk_set:
        return
    if not reverse:  # contact.lists.add(list_ids)
        handle_contact_added_to_lists(instance, list(pk_set))
    else:  # contact_list.contacts.add(contact_ids)
        for contact in Contact.objects.filter(pk__in=pk_set).select_related("owner"):
            handle_contact_added_to_lists(contact, [instance.pk])
