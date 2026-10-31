"""
Guilds -- the communities that posts are filed under.

The product calls these "guilds"; the historical schema called the table
``boards``, and that name is kept so a database that still carries the original
table keeps its guilds across an upgrade.  See MIGRATION_NOTES.md §5.

``GuildMember`` has no counterpart in the historical schema: membership and
per-guild moderators are additions made for this feature, not restorations.
"""

from sqlalchemy import *
from sqlalchemy.orm import relationship
from time import time

from ruqqus.helpers.base36 import *
from ruqqus.__main__ import Base, db
from .user import User


class Guild(Base):

    __tablename__="boards"

    id=Column(Integer, primary_key=True)
    board_name=Column(String(64), default=None)
    is_banned=Column(Boolean, default=False)
    created_utc=Column(BigInteger, default=0)

    # None of these were on the historical table.
    created_by=Column(Integer, ForeignKey("users.id"), default=None)
    description=Column(String(512), default="")
    description_html=Column(String(1024), default="")

    submissions=relationship("Submission", lazy="dynamic", backref="guild")
    members=relationship("GuildMember", lazy="dynamic", backref="guild")

    def __init__(self, **kwargs):

        kwargs["created_utc"]=int(time())

        super().__init__(**kwargs)

    @property
    def base36id(self):
        return base36encode(self.id)

    @property
    def fullname(self):
        # t4_ is unused: t1_ is User, t2_ Submission, t3_ Comment.
        return f"t4_{self.base36id}"

    @property
    def url(self):
        return f"/+{self.board_name}"

    @property
    def permalink(self):
        return self.url

    @property
    def post_count(self):
        return self.submissions.filter_by(is_banned=False).count()

    @property
    def member_count(self):
        return self.members.count()

    def has_member(self, user):

        if not user:
            return False

        return self.members.filter_by(user_id=user.id).first() is not None

    def is_moderator(self, user):

        if not user:
            return False

        # The founder moderates regardless of the membership row.
        if self.created_by == user.id:
            return True

        member=self.members.filter_by(user_id=user.id).first()
        return bool(member and member.is_mod)

    @property
    def moderators(self):

        founder=db.query(User).filter_by(id=self.created_by).first() if self.created_by else None

        listed=[m.user for m in self.members.filter_by(is_mod=True).all()]

        if founder and all(founder.id != u.id for u in listed):
            listed.insert(0, founder)

        return listed

    def __repr__(self):
        return f"<Guild(board_name={self.board_name})>"


class GuildMember(Base):

    __tablename__="board_members"

    id=Column(Integer, primary_key=True)
    board_id=Column(Integer, ForeignKey("boards.id"))
    user_id=Column(Integer, ForeignKey("users.id"))
    is_mod=Column(Boolean, default=False)
    created_utc=Column(BigInteger, default=0)

    user=relationship("User", uselist=False)

    def __init__(self, **kwargs):

        kwargs["created_utc"]=int(time())

        super().__init__(**kwargs)

    def __repr__(self):
        return f"<GuildMember(board_id={self.board_id}, user_id={self.user_id})>"