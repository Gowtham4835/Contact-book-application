from django.urls import path

from .api import ContactSessionAPIView, DuplicateContactsAPIView


urlpatterns = [
    path("contacts/duplicates/", DuplicateContactsAPIView.as_view(), name="contact_duplicates"),
    path("session/", ContactSessionAPIView.as_view(), name="contact_session"),
]