from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .models import Comment, Follow, Like, Post

User = get_user_model()
AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


class Base(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", "alice@example.com", "pw-alice-123")
        self.bob = User.objects.create_user("bob", "bob@example.com", "pw-bob-123")
        self.cara = User.objects.create_user("cara", "cara@example.com", "pw-cara-123")
        self.client.login(username="alice", password="pw-alice-123")


class ModelTests(Base):
    def test_profile_created_automatically(self):
        self.assertTrue(hasattr(self.alice, "profile"))

    def test_cannot_like_twice(self):
        post = Post.objects.create(author=self.bob, content="hi")
        Like.objects.create(user=self.alice, post=post)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Like.objects.create(user=self.alice, post=post)

    def test_cannot_follow_twice_or_self(self):
        Follow.objects.create(follower=self.alice, following=self.bob)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Follow.objects.create(follower=self.alice, following=self.bob)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Follow.objects.create(follower=self.alice, following=self.alice)


class AuthTests(TestCase):
    def test_register_logs_in_and_creates_profile(self):
        response = self.client.post(
            reverse("register"),
            {"username": "newbie", "email": "n@example.com",
             "password1": "a-Strong-pass-42", "password2": "a-Strong-pass-42"},
        )
        self.assertRedirects(response, reverse("people"))
        self.assertTrue(User.objects.get(username="newbie").profile)

    def test_duplicate_email_rejected(self):
        User.objects.create_user("x", "dup@example.com", "pw")
        response = self.client.post(
            reverse("register"),
            {"username": "y", "email": "DUP@example.com",
             "password1": "a-Strong-pass-42", "password2": "a-Strong-pass-42"},
        )
        self.assertContains(response, "already exists")

    def test_pages_require_login(self):
        for name in ("home", "explore", "people"):
            response = self.client.get(reverse(name))
            self.assertRedirects(response, f"{reverse('login')}?next={reverse(name)}")


class PostTests(Base):
    def test_create_post(self):
        self.client.post(reverse("home"), {"content": "  hello world  "})
        self.assertEqual(Post.objects.get().content, "hello world")

    def test_blank_post_rejected(self):
        response = self.client.post(reverse("home"), {"content": "   "})
        self.assertEqual(Post.objects.count(), 0)
        self.assertContains(response, "Write something before posting.")

    def test_only_author_can_delete(self):
        post = Post.objects.create(author=self.bob, content="bob's post")
        response = self.client.post(reverse("post_delete", args=[post.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Post.objects.filter(pk=post.pk).exists())

        own = Post.objects.create(author=self.alice, content="mine")
        self.client.post(reverse("post_delete", args=[own.pk]))
        self.assertFalse(Post.objects.filter(pk=own.pk).exists())

    def test_delete_requires_post_method(self):
        own = Post.objects.create(author=self.alice, content="mine")
        self.assertEqual(self.client.get(reverse("post_delete", args=[own.pk])).status_code, 405)


class FeedTests(Base):
    def test_home_feed_shows_own_and_followed_only(self):
        Post.objects.create(author=self.alice, content="from alice")
        Post.objects.create(author=self.bob, content="from bob")
        Post.objects.create(author=self.cara, content="from cara")
        Follow.objects.create(follower=self.alice, following=self.bob)

        response = self.client.get(reverse("home"))
        self.assertContains(response, "from alice")
        self.assertContains(response, "from bob")
        self.assertNotContains(response, "from cara")

        response = self.client.get(reverse("explore"))
        self.assertContains(response, "from cara")

    def test_pagination(self):
        for i in range(25):
            Post.objects.create(author=self.alice, content=f"post {i}")
        self.assertEqual(len(self.client.get(reverse("home")).context["page"]), 10)
        self.assertEqual(len(self.client.get(reverse("home") + "?page=3").context["page"]), 5)


class LikeTests(Base):
    def test_like_toggle_json(self):
        post = Post.objects.create(author=self.bob, content="x")
        url = reverse("like_toggle", args=[post.pk])
        r = self.client.post(url, **AJAX)
        self.assertEqual(r.json(), {"liked": True, "count": 1})
        r = self.client.post(url, **AJAX)
        self.assertEqual(r.json(), {"liked": False, "count": 0})

    def test_like_without_js_redirects(self):
        post = Post.objects.create(author=self.bob, content="x")
        r = self.client.post(reverse("like_toggle", args=[post.pk]), {"next": reverse("explore")})
        self.assertRedirects(r, reverse("explore"))

    def test_open_redirect_blocked(self):
        post = Post.objects.create(author=self.bob, content="x")
        r = self.client.post(reverse("like_toggle", args=[post.pk]), {"next": "https://evil.example/"})
        self.assertRedirects(r, post.get_absolute_url())

    def test_liked_state_rendered(self):
        post = Post.objects.create(author=self.bob, content="x")
        Like.objects.create(user=self.alice, post=post)
        response = self.client.get(reverse("explore"))
        self.assertContains(response, "is-liked")


class CommentTests(Base):
    def setUp(self):
        super().setUp()
        self.post = Post.objects.create(author=self.bob, content="bob's post")

    def test_add_comment(self):
        self.client.post(reverse("comment_add", args=[self.post.pk]), {"text": "nice"})
        self.assertEqual(Comment.objects.get().text, "nice")
        self.assertContains(self.client.get(self.post.get_absolute_url()), "nice")

    def test_author_and_post_owner_can_delete_others_cannot(self):
        comment = Comment.objects.create(post=self.post, author=self.cara, text="hi")
        # alice is neither the comment author nor the post owner
        self.assertEqual(self.client.post(reverse("comment_delete", args=[comment.pk])).status_code, 403)
        # bob owns the post
        self.client.login(username="bob", password="pw-bob-123")
        self.client.post(reverse("comment_delete", args=[comment.pk]))
        self.assertFalse(Comment.objects.exists())


class FollowTests(Base):
    def test_follow_toggle_json(self):
        url = reverse("follow_toggle", args=["bob"])
        self.assertEqual(self.client.post(url, **AJAX).json(), {"following": True, "followers": 1})
        self.assertEqual(self.client.post(url, **AJAX).json(), {"following": False, "followers": 0})

    def test_cannot_follow_self(self):
        r = self.client.post(reverse("follow_toggle", args=["alice"]), **AJAX)
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Follow.objects.exists())

    def test_profile_counts_and_lists(self):
        Follow.objects.create(follower=self.alice, following=self.bob)
        Follow.objects.create(follower=self.cara, following=self.bob)
        r = self.client.get(reverse("profile", args=["bob"]))
        self.assertEqual(r.context["follower_count"], 2)
        self.assertTrue(r.context["is_following"])
        r = self.client.get(reverse("followers", args=["bob"]))
        self.assertEqual({u.username for u in r.context["page"]}, {"alice", "cara"})
        r = self.client.get(reverse("following", args=["alice"]))
        self.assertEqual({u.username for u in r.context["page"]}, {"bob"})

    def test_people_search(self):
        r = self.client.get(reverse("people"), {"q": "ca"})
        self.assertEqual([u.username for u in r.context["page"]], ["cara"])

    def test_edit_profile(self):
        r = self.client.post(reverse("profile_edit"), {
            "first_name": "Alice", "last_name": "Ng", "email": "alice@example.com",
            "bio": "Hello!", "location": "Chennai",
        })
        self.assertRedirects(r, reverse("profile", args=["alice"]))
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.profile.bio, "Hello!")
        self.assertEqual(self.alice.get_full_name(), "Alice Ng")
