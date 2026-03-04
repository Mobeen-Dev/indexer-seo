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

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    shop = Column(String, index=True, nullable=False)
    baseId = Column(BigInteger, nullable=False)
    webUrl = Column(Text, nullable=False)

    indexAction = Column(
        SQLEnum(IndexAction, name="IndexAction", create_type=False),
        index=True,
        nullable=False,
        default=IndexAction.INDEX,
        server_default="INDEX",
    )
    status = Column(
        SQLEnum(UrlStatus, name="UrlStatus", create_type=False),
        index=True,
        nullable=False,
        default=UrlStatus.PENDING,
        server_default="PENDING",
    )

    attempts = Column(Integer, nullable=False, default=2, server_default="2")
    isGoogleIndexed = Column(Boolean, nullable=False, default=False, server_default="false")
    isBingIndexed = Column(Boolean, nullable=False, default=False, server_default="false")
    submittedAt = Column(DateTime, index=True)
    lastEventAt = Column(DateTime)
    lastTriedAt = Column(DateTime)
    lastIndexedAt = Column(DateTime)
    meta = Column("metadata", JSONB)

    # Constraints (names match Prisma-generated migrations)
    __table_args__ = (
        UniqueConstraint("shop", "webUrl", name="UrlEntry_shop_webUrl_key"),
        UniqueConstraint("shop", "baseId", name="UrlEntry_shop_baseId_key"),
        Index("UrlEntry_shop_idx", "shop"),
        Index("UrlEntry_status_idx", "status"),
        Index("UrlEntry_indexAction_idx", "indexAction"),
        Index(
            "UrlEntry_lastIndexedAt_attempts_idx",
            "lastIndexedAt",
            "attempts",
            postgresql_ops={
                "lastIndexedAt": "ASC",
                "attempts": "ASC",
            },
        ),
        Index(
            "UrlEntry_shop_status_lastIndexedAt_attempts_idx",
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
    __tablename__ = "IndexTask"

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
        UniqueConstraint("shop", "url", name="IndexTask_shop_url_key"),
        Index("IndexTask_shop_isCompleted_idx", "shop", "isCompleted"),
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
