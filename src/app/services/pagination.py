from dataclasses import dataclass
from math import ceil


DEFAULT_PER_PAGE = 20


@dataclass(slots=True)
class PaginationResult:
    items: list
    page: int
    per_page: int
    total: int
    pages: int

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.pages

    @property
    def prev_page(self) -> int | None:
        if not self.has_prev:
            return None
        return self.page - 1

    @property
    def next_page(self) -> int | None:
        if not self.has_next:
            return None
        return self.page + 1


def normalize_page(raw_value: str | None) -> int:
    try:
        page = int(str(raw_value or "").strip() or "1")
    except ValueError:
        return 1
    return max(page, 1)


def paginate_query(query, *, page: int, per_page: int = DEFAULT_PER_PAGE) -> PaginationResult:
    total = query.count()
    pages = max(ceil(total / per_page), 1)
    current_page = min(page, pages)
    items = query.offset((current_page - 1) * per_page).limit(per_page).all()
    return PaginationResult(
        items=items,
        page=current_page,
        per_page=per_page,
        total=total,
        pages=pages,
    )
