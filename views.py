from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import (
    CommentForm,
    PostForm,
    ProfileForm,
    RegisterForm,
    UserNameForm,
)
from .models import Comment, Follow, Like, Post, Profile

User = get_user_model()
PAGE_SIZE = 10


# --- helpers ------------------------------------------------------------
def _wants_json(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _next_url(request, default):
    """Where to go after a form POST. Only same-site URLs are allowed."""
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return default


def _paginate(request, queryset):
    return Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))


def _posts_for(viewer):
    """Posts annotated with like/comment counts and whether `viewer` liked them."""
    return (
        Post.objects.select_related("author", "author__profile")
        .annotate(
            like_count=Count("likes", distinct=True),
            comment_count=Count("comments", distinct=True),
            liked_by_me=Exists(Like.objects.filter(post=OuterRef("pk"), user=viewer)),
        )
        # Meta.ordering is ignored on annotated (GROUP BY) queries, so order explicitly.
        .order_by("-created_at", "-id")
    )


def _following_ids(user):
    return set(user.following_rel.values_list("following_id", flat=True))


def _suggestions(user, limit=5):
    """Popular people the user doesn't follow yet."""
    return (
        User.objects.exclude(pk=user.pk)
        .exclude(follower_rel__follower=user)
        .select_related("profile")
        .annotate(follower_count=Count("follower_rel", distinct=True))
        .order_by("-follower_count", "-date_joined")[:limit]
    )


def _flash_form_errors(request, form):
    for errors in form.errors.values():
        for error in errors:
            messages.error(request, error)


# --- auth ---------------------------------------------------------------
def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, f"Welcome to Nook, {user.username}. Follow a few people to fill your feed.")
        return redirect("people")
    return render(request, "registration/register.html", {"form": form})


# --- feeds --------------------------------------------------------------
@login_required
def home(request):
    """Feed of your own posts and posts from people you follow, plus the composer."""
    if request.method == "POST":
        form = PostForm(request.POST, request.FILES)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            post.save()
            messages.success(request, "Posted.")
            return redirect("home")
    else:
        form = PostForm()

    following = request.user.following_rel.values("following_id")
    posts = _posts_for(request.user).filter(
        Q(author=request.user) | Q(author_id__in=following)
    )
    return render(
        request,
        "social/feed.html",
        {
            "page": _paginate(request, posts),
            "form": form,
            "nav": "home",
            "tab": "home",
            "suggestions": _suggestions(request.user),
        },
    )


@login_required
def explore(request):
    """Every post on the site, newest first."""
    return render(
        request,
        "social/feed.html",
        {
            "page": _paginate(request, _posts_for(request.user)),
            "nav": "home",
            "tab": "explore",
            "suggestions": _suggestions(request.user),
        },
    )


@login_required
def people(request):
    query = request.GET.get("q", "").strip()
    users = User.objects.exclude(pk=request.user.pk).select_related("profile")
    if query:
        users = users.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )
    users = users.annotate(follower_count=Count("follower_rel", distinct=True)).order_by(
        "-follower_count", "username"
    )
    return render(
        request,
        "social/people.html",
        {
            "page": _paginate(request, users),
            "query": query,
            "following_ids": _following_ids(request.user),
            "nav": "people",
        },
    )


# --- posts --------------------------------------------------------------
@login_required
def post_detail(request, pk):
    post = get_object_or_404(_posts_for(request.user), pk=pk)
    comments = post.comments.select_related("author", "author__profile")
    return render(
        request,
        "social/post_detail.html",
        {
            "post": post,
            "comments": comments,
            "comment_form": CommentForm(),
            "nav": "home",
        },
    )


@require_POST
@login_required
def post_delete(request, pk):
    post = get_object_or_404(Post, pk=pk)
    if post.author_id != request.user.id:
        raise PermissionDenied
    detail_url = post.get_absolute_url()
    post.delete()
    messages.success(request, "Post deleted.")
    target = _next_url(request, reverse("home"))
    if target.startswith(detail_url):  # don't bounce back to the deleted post
        target = reverse("home")
    return redirect(target)


@require_POST
@login_required
def like_toggle(request, pk):
    post = get_object_or_404(Post, pk=pk)
    like, created = Like.objects.get_or_create(user=request.user, post=post)
    if not created:
        like.delete()
    if _wants_json(request):
        return JsonResponse({"liked": created, "count": post.likes.count()})
    return redirect(_next_url(request, post.get_absolute_url()))


# --- comments -----------------------------------------------------------
@require_POST
@login_required
def comment_add(request, pk):
    post = get_object_or_404(Post, pk=pk)
    form = CommentForm(request.POST)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.post = post
        comment.author = request.user
        comment.save()
    else:
        _flash_form_errors(request, form)
    return redirect(f"{post.get_absolute_url()}#comments")


@require_POST
@login_required
def comment_delete(request, pk):
    comment = get_object_or_404(Comment, pk=pk)
    # A comment can be removed by its author or by the owner of the post.
    if request.user.id not in (comment.author_id, comment.post.author_id):
        raise PermissionDenied
    post = comment.post
    comment.delete()
    messages.success(request, "Comment deleted.")
    return redirect(f"{post.get_absolute_url()}#comments")


# --- profiles & follows -------------------------------------------------
@login_required
def profile(request, username):
    owner = get_object_or_404(User.objects.select_related("profile"), username=username)
    posts = _posts_for(request.user).filter(author=owner)
    return render(
        request,
        "social/profile.html",
        {
            "owner": owner,
            "page": _paginate(request, posts),
            "post_count": owner.posts.count(),
            "follower_count": owner.follower_rel.count(),
            "following_count": owner.following_rel.count(),
            "is_following": Follow.objects.filter(
                follower=request.user, following=owner
            ).exists(),
            "nav": "me" if owner == request.user else "",
        },
    )


@login_required
def profile_edit(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    user_form = UserNameForm(request.POST or None, instance=request.user)
    profile_form = ProfileForm(request.POST or None, request.FILES or None, instance=profile)
    if request.method == "POST" and user_form.is_valid() and profile_form.is_valid():
        user_form.save()
        profile_form.save()
        messages.success(request, "Profile saved.")
        return redirect("profile", username=request.user.username)
    return render(
        request,
        "social/profile_edit.html",
        {"user_form": user_form, "profile_form": profile_form, "nav": "me"},
    )


@require_POST
@login_required
def follow_toggle(request, username):
    target = get_object_or_404(User, username=username)
    if target == request.user:
        if _wants_json(request):
            return JsonResponse({"error": "You can't follow yourself."}, status=400)
        messages.error(request, "You can't follow yourself.")
        return redirect("profile", username=username)

    rel, created = Follow.objects.get_or_create(follower=request.user, following=target)
    if not created:
        rel.delete()
    if _wants_json(request):
        return JsonResponse(
            {"following": created, "followers": target.follower_rel.count()}
        )
    return redirect(_next_url(request, reverse("profile", args=[username])))


def _user_list(request, username, kind):
    owner = get_object_or_404(User.objects.select_related("profile"), username=username)
    if kind == "followers":
        users = User.objects.filter(following_rel__following=owner)
    else:
        users = User.objects.filter(follower_rel__follower=owner)
    users = users.select_related("profile").order_by("username")
    return render(
        request,
        "social/user_list.html",
        {
            "owner": owner,
            "kind": kind,
            "page": _paginate(request, users),
            "following_ids": _following_ids(request.user),
            "nav": "me" if owner == request.user else "",
        },
    )


@login_required
def followers(request, username):
    return _user_list(request, username, "followers")


@login_required
def following(request, username):
    return _user_list(request, username, "following")
