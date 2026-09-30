from django.contrib import admin

from .models import Comment, Follow, Like, Post, Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "location")
    search_fields = ("user__username", "bio")


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("author", "short_content", "created_at")
    list_filter = ("created_at",)
    search_fields = ("content", "author__username")

    @admin.display(description="content")
    def short_content(self, obj):
        return obj.content[:60]
