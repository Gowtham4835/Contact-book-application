from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from .models import Contact


User = get_user_model()

class RegistrationForm(forms.Form):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"class": "form-control"})
    )
    
    password = forms.CharField(
        required=True,
        validators=[validate_password],
        widget=forms.PasswordInput(attrs={"class": "form-control"})
    )

    def clean_password(self):
        password = self.cleaned_data["password"]
        email = self.cleaned_data.get("email")
        if email:
            validate_password(password, user=User(username=email, email=email))
        return password
    
    confirm_password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(attrs={"class": "form-control"})
    )
    
    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        if User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")
        
        if password and confirm_password:
            if password != confirm_password:
                self.add_error("confirm_password", "Passwords do not match.")
        return cleaned_data
            
class LoginForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": "form-control"})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control"})
    )

class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = [
            "name",
            "phone_number",
            "contact_picture",
            "contact_group",
            "email",
            "birthday",
            "anniversary",
            "reminder_date",
            "reminder_note",
        ]
        
        widgets = {
            "name" : forms.TextInput(attrs={"class":"form-control"}),
            "phone_number" : forms.TextInput(attrs={"class":"form-control"}),
            "contact_picture" : forms.ClearableFileInput(attrs={"class":"form-control"}),
            "contact_group" : forms.Select(attrs={"class":"form-select"}),
            "email" : forms.EmailInput(attrs={"class":"form-control"}),
            "birthday": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "anniversary": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "reminder_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "reminder_note": forms.TextInput(attrs={"class": "form-control"}),
        }