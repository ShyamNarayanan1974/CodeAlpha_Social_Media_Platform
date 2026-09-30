from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import Comment, Post, Profile

User = get_user_model()
MAX_IMAGE_MB = 5


def _check_image_size(image):
    if image and image.size > MAX_IMAGE_MB * 1024 * 1024:
        raise forms.ValidationError(f"Images must be smaller than {MAX_IMAGE_MB} MB.")
    return image


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class PostForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ["content", "image"]
        widgets = {
            "content": forms.Textarea(
                attrs={"rows": 2, "maxlength": 500, "placeholder": "What's on your mind?"}
            ),
            "image": forms.ClearableFileInput(attrs={"accept": "image/*"}),
        }
        error_messages = {"content": {"required": "Write something before posting."}}

    def clean_image(self):
        return _check_image_size(self.cleaned_data.get("image"))


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ["text"]
        widgets = {
            "text": forms.TextInput(
                attrs={"maxlength": 300, "placeholder": "Add a comment", "autocomplete": "off"}
            )
        }
        error_messages = {"text": {"required": "Write a comment before sending."}}



class UserNameForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Another account already uses this email.")
        return email


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["bio", "location", "avatar"]
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 3, "maxlength": 280}),
            "avatar": forms.FileInput(attrs={"accept": "image/*"}),
        }

    def clean_avatar(self):
        return _check_image_size(self.cleaned_data.get("avatar"))
