"""Tests for database migrations using Alembic."""

import pytest
from alembic.command import upgrade, downgrade
from alembic.config import Config
from alembic import script
from alembic.runtime import migration
from sqlalchemy import inspect, text


def get_alembic_config():
    """Get Alembic config object pointing to the alembic.ini."""
    import os
    alembic_ini = os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
    return Config(alembic_ini)


class TestAlembicMigration:
    """Tests for Alembic database migrations."""

    def test_alembic_script_directory_exists(self):
        """Alembic script directory should exist."""
        import os
        script_dir = os.path.join(os.path.dirname(__file__), "..", "alembic", "versions")
        assert os.path.isdir(script_dir)

    def test_alembic_env_exists(self):
        """Alembic env.py should exist."""
        import os
        env_path = os.path.join(os.path.dirname(__file__), "..", "alembic", "env.py")
        assert os.path.isfile(env_path)

    def test_alembic_ini_exists(self):
        """Alembic alembic.ini should exist."""
        import os
        ini_path = os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
        assert os.path.isfile(ini_path)

    def test_all_models_registered_with_base(self):
        """All models should be registered with Base metadata."""
        from models.base import Base
        import models  # noqa: F401

        expected_tables = {
            "users",
            "posts",
            "comments",
            "groups",
            "group_memberships",
            "notifications",
        }
        actual_tables = set(Base.metadata.tables.keys())
        assert expected_tables.issubset(actual_tables)

    def test_users_table_columns(self):
        """Users table should have all required columns."""
        from models.base import Base
        import models  # noqa: F401

        columns = set(Base.metadata.tables["users"].columns.keys())
        expected = {
            "id", "email", "username", "password_hash",
            "full_name", "avatar_url", "is_verified",
            "created_at", "updated_at",
        }
        assert expected.issubset(columns)

    def test_posts_table_columns(self):
        """Posts table should have all required columns."""
        from models.base import Base
        import models  # noqa: F401

        columns = set(Base.metadata.tables["posts"].columns.keys())
        expected = {
            "id", "title", "content", "author_id", "group_id",
            "category", "image_url", "view_count", "like_count",
            "created_at", "updated_at",
        }
        assert expected.issubset(columns)

    def test_comments_table_columns(self):
        """Comments table should have all required columns."""
        from models.base import Base
        import models  # noqa: F401

        columns = set(Base.metadata.tables["comments"].columns.keys())
        expected = {
            "id", "post_id", "author_id", "content",
            "parent_id", "like_count", "created_at", "updated_at",
        }
        assert expected.issubset(columns)

    def test_groups_table_columns(self):
        """Groups table should have all required columns."""
        from models.base import Base
        import models  # noqa: F401

        columns = set(Base.metadata.tables["groups"].columns.keys())
        expected = {
            "id", "name", "description", "owner_id",
            "is_public", "member_count", "created_at", "updated_at",
        }
        assert expected.issubset(columns)

    def test_group_memberships_table_columns(self):
        """Group_memberships table should have all required columns."""
        from models.base import Base
        import models  # noqa: F401

        columns = set(Base.metadata.tables["group_memberships"].columns.keys())
        expected = {
            "id", "group_id", "user_id", "role",
            "joined_at", "is_active",
        }
        assert expected.issubset(columns)

    def test_notifications_table_columns(self):
        """Notifications table should have all required columns."""
        from models.base import Base
        import models  # noqa: F401

        columns = set(Base.metadata.tables["notifications"].columns.keys())
        expected = {
            "id", "user_id", "type", "title",
            "message", "is_read", "created_at", "updated_at",
        }
        assert expected.issubset(columns)

    def test_foreign_keys_posts(self):
        """Posts table should have correct foreign keys."""
        from models.base import Base
        import models  # noqa: F401

        posts_table = Base.metadata.tables["posts"]
        fks = {fk.target_fullname for fk in posts_table.foreign_keys}
        assert "users.id" in fks
        assert "groups.id" in fks

    def test_foreign_keys_comments(self):
        """Comments table should have correct foreign keys."""
        from models.base import Base
        import models  # noqa: F401

        comments_table = Base.metadata.tables["comments"]
        fks = {fk.target_fullname for fk in comments_table.foreign_keys}
        assert "posts.id" in fks
        assert "users.id" in fks
        assert "comments.id" in fks  # self-referential for parent_id

    def test_foreign_keys_groups(self):
        """Groups table should have correct foreign keys."""
        from models.base import Base
        import models  # noqa: F401

        groups_table = Base.metadata.tables["groups"]
        fks = {fk.target_fullname for fk in groups_table.foreign_keys}
        assert "users.id" in fks

    def test_foreign_keys_group_memberships(self):
        """Group_memberships table should have correct foreign keys."""
        from models.base import Base
        import models  # noqa: F401

        memberships_table = Base.metadata.tables["group_memberships"]
        fks = {fk.target_fullname for fk in memberships_table.foreign_keys}
        assert "groups.id" in fks
        assert "users.id" in fks

    def test_foreign_keys_notifications(self):
        """Notifications table should have correct foreign keys."""
        from models.base import Base
        import models  # noqa: F401

        notifications_table = Base.metadata.tables["notifications"]
        fks = {fk.target_fullname for fk in notifications_table.foreign_keys}
        assert "users.id" in fks

    def test_unique_constraints(self):
        """Tables should have correct unique constraints."""
        from models.base import Base
        import models  # noqa: F401

        users_table = Base.metadata.tables["users"]
        unique_constraints = [
            constraint for constraint in users_table.constraints
            if getattr(constraint, 'unique', False)
        ]
        assert len(unique_constraints) >= 2  # email and username

    def test_indexes_exist(self):
        """Tables should have indexes for foreign keys."""
        from models.base import Base
        import models  # noqa: F401

        posts_table = Base.metadata.tables["posts"]
        index_names = {idx.name for idx in posts_table.indexes}
        assert len(index_names) > 0
