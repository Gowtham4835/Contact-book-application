from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.views import View
from django.views.generic import TemplateView

from .forms import ContactForm
from .models import Contact
from .tasks import send_contact_event_email

def can_manage_all_contacts(user):
    return user.is_superuser or user.has_perm("contacts.manage_all_contacts")


class ContactListView(LoginRequiredMixin, TemplateView):
    template_name = "contacts/contact_list.html"

    @method_decorator(ensure_csrf_cookie)
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.has_perm("contacts.view_contact"):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class ContactFormView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            permission = "change_contact" if kwargs.get("pk") is not None else "add_contact"
            if not request.user.has_perm(f"contacts.{permission}"):
                raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_contact(self, request, pk):
        contacts = Contact.objects.all()
        if not can_manage_all_contacts(request.user):
            contacts = contacts.filter(user=request.user)
        return get_object_or_404(contacts, pk=pk)

    def get(self, request, pk=None):
        contact = None
        if pk is not None:
            contact = self.get_contact(request, pk)
            recent_ids = request.session.get("recent_contact_ids", [])
            request.session["recent_contact_ids"] = [contact.pk] + [
                item for item in recent_ids if item != contact.pk
            ][:9]

        form = ContactForm(instance=contact)
        return render(
            request,
            "contacts/contact_form.html",
            {"form": form, "contact": contact},
        )

    def post(self, request, pk=None):
        contact = self.get_contact(request, pk) if pk is not None else None
        form = ContactForm(
            request.POST,
            request.FILES,
            instance=contact,
        )

        if form.is_valid():
            if contact is None:
                form.instance.user = request.user

            saved_contact = form.save()
            event = "created" if contact is None else "updated"
            transaction.on_commit(
                lambda contact_id=saved_contact.pk, contact_event=event: send_contact_event_email.delay(
                    contact_id,
                    contact_event,
                ),
                robust=True,
            )
            return JsonResponse({
                "success": True,
                "message": "Contact saved successfully",
                "id": saved_contact.pk,
            })

        return JsonResponse({
            "success": False,
            "errors": form.errors.get_json_data(),
        }, status=400)

class ContactDeleteView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.has_perm("contacts.delete_contact"):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, pk):
        contacts = Contact.objects.all()
        if not can_manage_all_contacts(request.user):
            contacts = contacts.filter(user=request.user)
        contact = get_object_or_404(contacts, pk=pk)
        contact.delete()

        return JsonResponse({
            "success": True,
            "message": "Contact deleted successfully",
        })
        
        
        
            
            