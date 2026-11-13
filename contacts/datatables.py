from ajax_datatable.views import AjaxDatatableView
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.contrib.auth.mixins import LoginRequiredMixin
 
from .models import Contact
 
 
class ContactAjaxDatatableView(LoginRequiredMixin, AjaxDatatableView):
    model = Contact
    title = "Contacts"
    initial_order = [["name", "asc"]]
 
    column_defs = [
        {
            "name": "name",
            "title": "Name",
            "searchable": True,
            "orderable": True,
        },
        {
            "name": "phone_number",
            "title": "Phone Number",
            "searchable": True,
            "orderable": True,
        },
        {
            "name": "email",
            "title": "Email",
            "searchable": True,
            "orderable": True,
        },
        {
            "name": "pk",
            "title": "Actions",
            "searchable": False,
            "orderable": False,
        },
    ]

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.has_perm("contacts.view_contact"):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_initial_queryset(self, request=None):
        queryset = super().get_initial_queryset(request)
        if request is not None and not (
            request.user.is_superuser or request.user.has_perm("contacts.manage_all_contacts")
        ):
            queryset = queryset.filter(user=request.user)
        return queryset
 
    def customize_row(self, row, obj):
        edit_url = reverse(
            "contacts:contact_edit",
            args=[obj.pk],
        )
        delete_url = reverse(
            "contacts:contact_delete",
            args=[obj.pk],
        )
 
        actions = []
        if self.request.user.has_perm("contacts.change_contact"):
            actions.append(
                f'<button type="button" class="btn btn-sm btn-primary edit-contact" '
                f'data-url="{edit_url}" title="Edit contact" aria-label="Edit contact">'
                f'<i class="bi bi-pencil-square" aria-hidden="true"></i>'
                f'<span class="visually-hidden">Edit</span></button>'
            )
        if self.request.user.has_perm("contacts.delete_contact"):
            actions.append(
                f'<button type="button" class="btn btn-sm btn-danger delete-contact" '
                f'data-url="{delete_url}" title="Delete contact" aria-label="Delete contact">'
                f'<i class="bi bi-trash" aria-hidden="true"></i>'
                f'<span class="visually-hidden">Delete</span></button>'
            )
        row["pk"] = " ".join(actions)
 
        return row