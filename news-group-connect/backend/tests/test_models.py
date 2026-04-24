"""Tests for NewsGroup Connect models."""

import pytest
from datetime import datetime, timezone
from sqlalchemy import inspect

from models.base import Base, TimestampMixin
from models.user import User
from models.post import Post
from models.comment import Comment
from models.group import Group
from models.membership import GroupMembership
from models.notification import Notification


class TestBaseModel:
    """Tests for Base model class."""

    def test_base_is_declarative(self):
        """Base class should be a SQLAlchemy declarative base."""
        assert hasattr(Base, "metadata")
        assert hasattr(Base, "registry")

    def test_timestamp_mixin_has_created_at(self):
        """TimestampMixin should define created_at column."""
        assert hasattr(TimestampMixin, "created_at")

    def test_timestamp_mixin_has_updated_at(self):
        """TimestampMixin should define updated_at column."""
        assert hasattr(TimestampMixin, "updated_at")


class TestUserModel:
    """Tests for User model."""

    def test_user_table_name(self):
        """User model should have correct table name."""
        assert User.__tablename__ == "users"

    def test_user_has_required_fields(self):
        """User model should have all required columns."""
        columns = {c.key for c in User.__table__.columns}
        expected = {"id", "email", "username", "password_hash", "full_name", "avatar_url", "is_verified", "created_at", "updated_at"}
        assert expected.issubset(columns)

    def test_user_email_unique(self):
        """User email should be unique constraint."""
        email_col = User.__table__.columns["email"]
        assert email_col.unique is True

    def test_user_username_unique(self):
        """User username should be unique constraint."""
        username_col = User.__table__.columns["username"]
        assert username_col.unique is True

    def test_user_email_max_length(self):
        """User email should have max length of 255."""
        email_col = User.__table__.columns["email"]
        assert email_col.type.length == 255

    def test_user_username_max_length(self):
        """User username should have max length of 50."""
        username_col = User.__table__.columns["username"]
        assert username_col.type.length == 50

    def test_user_password_hash_not_nullable(self):
        """User password_hash should not be nullable."""
        col = User.__table__.columns["password_hash"]
        assert col.nullable is False

    def test_user_is_verified_defaults_false(self):
        """User is_verified should default to False."""
        col = User.__table__.columns["is_verified"]
        assert col.default is None or col.default.arg is False

    def test_user_has_posts_relationship(self):
        """User should have posts relationship."""
        assert hasattr(User, "posts")

    def test_user_has_comments_relationship(self):
        """User should have comments relationship."""
        assert hasattr(User, "comments")

    def test_user_has_owned_groups_relationship(self):
        """User should have owned_groups relationship."""
        assert hasattr(User, "owned_groups")

    def test_user_has_memberships_relationship(self):
        """User should have memberships relationship."""
        assert hasattr(User, "memberships")

    def test_user_has_notifications_relationship(self):
        """User should have notifications relationship."""
        assert hasattr(User, "notifications")

    def test_user_avatar_url_nullable(self):
        """User avatar_url should be nullable."""
        col = User.__table__.columns["avatar_url"]
        assert col.nullable is True

    def test_user_full_name_nullable(self):
        """User full_name should be nullable."""
        col = User.__table__.columns["full_name"]
        assert col.nullable is True


class TestPostModel:
    """Tests for Post model."""

    def test_post_table_name(self):
        """Post model should have correct table name."""
        assert Post.__tablename__ == "posts"

    def test_post_has_required_fields(self):
        """Post model should have all required columns."""
        columns = {c.key for c in Post.__table__.columns}
        expected = {"id", "title", "content", "author_id", "group_id", "category", "image_url", "view_count", "like_count", "created_at", "updated_at"}
        assert expected.issubset(columns)

    def test_post_title_max_length(self):
        """Post title should have max length of 200."""
        col = Post.__table__.columns["title"]
        assert col.type.length == 200

    def test_post_title_not_nullable(self):
        """Post title should not be nullable."""
        col = Post.__table__.columns["title"]
        assert col.nullable is False

    def test_post_content_not_nullable(self):
        """Post content should not be nullable."""
        col = Post.__table__.columns["content"]
        assert col.nullable is False

    def test_post_author_id_foreign_key(self):
        """Post author_id should reference users.id."""
        col = Post.__table__.columns["author_id"]
        assert col.nullable is False
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert fks[0].target_fullname == "users.id"

    def test_post_group_id_nullable(self):
        """Post group_id should be nullable."""
        col = Post.__table__.columns["group_id"]
        assert col.nullable is True

    def test_post_group_id_foreign_key(self):
        """Post group_id should reference groups.id."""
        col = Post.__table__.columns["group_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert fks[0].target_fullname == "groups.id"

    def test_post_category_max_length(self):
        """Post category should have max length of 50."""
        col = Post.__table__.columns["category"]
        assert col.type.length == 50

    def test_post_view_count_defaults_zero(self):
        """Post view_count should default to 0."""
        col = Post.__table__.columns["view_count"]
        assert col.default.arg == 0

    def test_post_like_count_defaults_zero(self):
        """Post like_count should default to 0."""
        col = Post.__table__.columns["like_count"]
        assert col.default.arg == 0

    def test_post_has_author_relationship(self):
        """Post should have author relationship."""
        assert hasattr(Post, "author")

    def test_post_has_group_relationship(self):
        """Post should have group relationship."""
        assert hasattr(Post, "group")

    def test_post_has_comments_relationship(self):
        """Post should have comments relationship."""
        assert hasattr(Post, "comments")


class TestCommentModel:
    """Tests for Comment model."""

    def test_comment_table_name(self):
        """Comment model should have correct table name."""
        assert Comment.__tablename__ == "comments"

    def test_comment_has_required_fields(self):
        """Comment model should have all required columns."""
        columns = {c.key for c in Comment.__table__.columns}
        expected = {"id", "post_id", "author_id", "content", "parent_id", "like_count", "created_at", "updated_at"}
        assert expected.issubset(columns)

    def test_comment_post_id_foreign_key(self):
        """Comment post_id should reference posts.id."""
        col = Comment.__table__.columns["post_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert fks[0].target_fullname == "posts.id"

    def test_comment_author_id_foreign_key(self):
        """Comment author_id should reference users.id."""
        col = Comment.__table__.columns["author_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert fks[0].target_fullname == "users.id"

    def test_comment_parent_id_self_reference(self):
        """Comment parent_id should reference comments.id."""
        col = Comment.__table__.columns["parent_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert fks[0].target_fullname == "comments.id"

    def test_comment_parent_id_nullable(self):
        """Comment parent_id should be nullable for top-level comments."""
        col = Comment.__table__.columns["parent_id"]
        assert col.nullable is True

    def test_comment_like_count_defaults_zero(self):
        """Comment like_count should default to 0."""
        col = Comment.__table__.columns["like_count"]
        assert col.default.arg == 0

    def test_comment_has_replies_relationship(self):
        """Comment should have replies relationship."""
        assert hasattr(Comment, "replies")

    def test_comment_has_parent_relationship(self):
        """Comment should have parent relationship."""
        assert hasattr(Comment, "parent")


class TestGroupModel:
    """Tests for Group model."""

    def test_group_table_name(self):
        """Group model should have correct table name."""
        assert Group.__tablename__ == "groups"

    def test_group_has_required_fields(self):
        """Group model should have all required columns."""
        columns = {c.key for c in Group.__table__.columns}
        expected = {"id", "name", "description", "owner_id", "is_public", "member_count", "created_at", "updated_at"}
        assert expected.issubset(columns)

    def test_group_name_unique(self):
        """Group name should be unique."""
        col = Group.__table__.columns["name"]
        assert col.unique is True

    def test_group_name_max_length(self):
        """Group name should have max length of 100."""
        col = Group.__table__.columns["name"]
        assert col.type.length == 100

    def test_group_owner_id_foreign_key(self):
        """Group owner_id should reference users.id."""
        col = Group.__table__.columns["owner_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert fks[0].target_fullname == "users.id"

    def test_group_is_public_defaults_true(self):
        """Group is_public should default to True."""
        col = Group.__table__.columns["is_public"]
        assert col.default.arg is True

    def test_group_member_count_defaults_zero(self):
        """Group member_count should default to 0."""
        col = Group.__table__.columns["member_count"]
        assert col.default.arg == 0

    def test_group_has_owner_relationship(self):
        """Group should have owner relationship."""
        assert hasattr(Group, "owner")

    def test_group_has_members_relationship(self):
        """Group should have members relationship."""
        assert hasattr(Group, "members")

    def test_group_has_posts_relationship(self):
        """Group should have posts relationship."""
        assert hasattr(Group, "posts")


class TestGroupMembershipModel:
    """Tests for GroupMembership model."""

    def test_membership_table_name(self):
        """GroupMembership model should have correct table name."""
        assert GroupMembership.__tablename__ == "group_memberships"

    def test_membership_has_required_fields(self):
        """GroupMembership model should have all required columns."""
        columns = {c.key for c in GroupMembership.__table__.columns}
        expected = {"id", "group_id", "user_id", "role", "joined_at", "is_active"}
        assert expected.issubset(columns)

    def test_membership_group_id_foreign_key(self):
        """GroupMembership group_id should reference groups.id."""
        col = GroupMembership.__table__.columns["group_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert fks[0].target_fullname == "groups.id"

    def test_membership_user_id_foreign_key(self):
        """GroupMembership user_id should reference users.id."""
        col = GroupMembership.__table__.columns["user_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert fks[0].target_fullname == "users.id"

    def test_membership_role_defaults_member(self):
        """GroupMembership role should default to 'member'."""
        col = GroupMembership.__table__.columns["role"]
        assert col.default.arg == "member"

    def test_membership_is_active_defaults_true(self):
        """GroupMembership is_active should default to True."""
        col = GroupMembership.__table__.columns["is_active"]
        assert col.default.arg is True

    def test_membership_has_group_relationship(self):
        """GroupMembership should have group relationship."""
        assert hasattr(GroupMembership, "group")

    def test_membership_has_user_relationship(self):
        """GroupMembership should have user relationship."""
        assert hasattr(GroupMembership, "user")


class TestNotificationModel:
    """Tests for Notification model."""

    def test_notification_table_name(self):
        """Notification model should have correct table name."""
        assert Notification.__tablename__ == "notifications"

    def test_notification_has_required_fields(self):
        """Notification model should have all required columns."""
        columns = {c.key for c in Notification.__table__.columns}
        expected = {"id", "user_id", "type", "title", "message", "is_read", "created_at", "updated_at"}
        assert expected.issubset(columns)

    def test_notification_user_id_foreign_key(self):
        """Notification user_id should reference users.id."""
        col = Notification.__table__.columns["user_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert fks[0].target_fullname == "users.id"

    def test_notification_type_max_length(self):
        """Notification type should have max length of 20."""
        col = Notification.__table__.columns["type"]
        assert col.type.length == 20

    def test_notification_title_max_length(self):
        """Notification title should have max length of 200."""
        col = Notification.__table__.columns["title"]
        assert col.type.length == 200

    def test_notification_is_read_defaults_false(self):
        """Notification is_read should default to False."""
        col = Notification.__table__.columns["is_read"]
        assert col.default.arg is False

    def test_notification_has_user_relationship(self):
        """Notification should have user relationship."""
        assert hasattr(Notification, "user")
