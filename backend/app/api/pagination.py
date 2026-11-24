from __future__ import annotations

from typing import Any

from fastapi import Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


class PageParams:
    def __init__(self, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200)):
        self.page = page
        self.page_size = page_size


def paginate(db: Session, stmt: Select, params: PageParams, schema) -> dict[str, Any]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.offset((params.page - 1) * params.page_size).limit(params.page_size)).unique().all()
    return {
        "items": [schema.model_validate(r) for r in rows],
        "total": total, "page": params.page, "page_size": params.page_size,
    }
