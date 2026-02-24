from sqlalchemy import (
    Column,
    String,
    DateTime,
    BigInteger,
    Boolean,
    Integer,
    Text,
    Index,
    UniqueConstraint,
)
from dataclasses import dataclass
import uuid
from typing import Dict, List, Literal
from enum import Enum as PyEnum
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base

# ---------------- SQLALCHEMY MODELS ----------------

Base = declarative_base()


class UrlStatus(PyEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class IndexAction(PyEnum):
    INDEX = "INDEX"  # submit/update
    DELETE = "DELETE"  # remove from index
    IGNORE = "IGNORE"  # do nothing


class Auth(Base):
    __tablename__ = "Auth"

    # primary
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    # shop / display details
    shop = Column(
        String,
        nullable=False,
        unique=True,
        index=True,
    )

    # provider-specific configuration
    googleConfig = Column(
        Text,
        nullable=True,  # String? in Prisma
    )

    bingApiKey = Column(
        String,
        nullable=True,  # String? in Prisma
    )

    # flexible fields
    settings = Column(
        JSONB,
        nullable=False,
    )

    createdAt = Column(
        DateTime(timezone=True),
    )

    updatedAt = Column(
        DateTime(timezone=True),
        nullable=False,
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "shop": self.shop,
            "googleConfig": self.googleConfig,
            "bingApiKey": self.bingApiKey,
            "settings": self.settings,
            "createdAt": self.createdAt.isoformat() if self.createdAt else None,
            "updatedAt": self.updatedAt.isoformat() if self.updatedAt else None,
        }


class UrlEntry(Base):
    __tablename__ = "UrlEntry"

    id = Column(String, primary_key=True)
    shop = Column(String, index=True, nullable=False)
    baseId = Column(BigInteger, nullable=False)
    webUrl = Column(Text, nullable=False)

    indexAction = Column(SQLEnum(IndexAction, name="indexaction"), index=True)
    status = Column(SQLEnum(UrlStatus, name="urlstatus"), index=True)

    attempts = Column(Integer)
    isGoogleIndexed = Column(Boolean, nullable=False, default=False)
    isBingIndexed = Column(Boolean, nullable=False, default=False)
    submittedAt = Column(DateTime, index=True)
    lastEventAt = Column(DateTime)
    lastTriedAt = Column(DateTime)
    lastIndexedAt = Column(DateTime)
    meta = Column("metadata", JSONB)

    # Constraints
    __table_args__ = (
        UniqueConstraint("shop", "webUrl", name="uq_url_entry_shop_weburl"),
        UniqueConstraint("shop", "baseId", name="uq_url_entry_shop_baseid"),
        Index("ix_url_entry_shop", "shop"),
        Index("ix_url_entry_status", "status"),
        Index("ix_url_entry_indexaction", "indexAction"),
        # Performance-focused ordered indexes
        Index(
            "ix_url_entry_lastindexed_attempts",
            "lastIndexedAt",
            "attempts",
            postgresql_ops={
                "lastIndexedAt": "ASC",
                "attempts": "ASC",
            },
        ),
        Index(
            "ix_url_entry_shop_status_lastindexed_attempts",
            "shop",
            "status",
            "lastIndexedAt",
            "attempts",
            postgresql_ops={
                "lastIndexedAt": "ASC",
                "attempts": "ASC",
            },
        ),
    )


class IndexTask(Base):
    __tablename__ = "index_task"

    id = Column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    shop = Column(String, nullable=False)
    url = Column(String, nullable=False)

    isCompleted = Column(
        Boolean,
        nullable=False,
        server_default="false",
    )

    createdAt = Column(
        DateTime(timezone=True),
        nullable=False,
    )

    completedAt = Column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("shop", "url", name="uq_index_task_shop_url"),
        Index("ix_index_task_shop_iscompleted", "shop", "isCompleted"),
    )


IndexActionStr = Literal["INDEX", "DELETE"]


@dataclass
class UrlItem:
    webUrl: str
    attempts: int

    def to_dict(self) -> dict:
        return {
            "webUrl": self.webUrl,
            "attempts": self.attempts,
        }


@dataclass
class UrlIndexBatchJob:
    jobType: Literal["URL_INDEXING_BATCH"]
    version: int
    # provider: Literal["BING", "GOOGLE"]
    actions: Dict[IndexActionStr, List[Dict]]
    auth: Auth
    shop: str

    def to_dict(self) -> dict:
        return {
            "jobType": self.jobType,
            "version": self.version,
            "shop": self.shop,
            "actions": self.actions,
            "auth": self.auth,
        }
