from django.urls import path
 
from .views import (
    ContactListView,
    ContactFormView,
    ContactDeleteView,
)
from .datatables import ContactAjaxDatatableView
 
app_name = "contacts"
 
urlpatterns = [
    path("", ContactListView.as_view(), name="contact_list"),
    path(
        "create/",
        ContactFormView.as_view(),
        name="contact_create",
    ),
    path(
        "<int:pk>/edit/",
        ContactFormView.as_view(),
        name="contact_edit",
    ),
    path(
        "<int:pk>/delete/",
        ContactDeleteView.as_view(),
        name="contact_delete",
    ),
    path(
        "ajax/contacts/",
        ContactAjaxDatatableView.as_view(),
        name="contact_datatable",
    ),
]