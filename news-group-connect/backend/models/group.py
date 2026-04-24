"""Group ORM model for NewsGroup Connect."""

from sqlalchemy import Boolean, Integer, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


class Group(Base, TimestampMixin):
    """Group model for communities."""

    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    owner = relationship("User", back_populates="owned_groups")
    members = relationship("GroupMembership", back_populates="group", lazy="selectin")
    posts = relationship("Post", back_populates="group", lazy="selectin")
