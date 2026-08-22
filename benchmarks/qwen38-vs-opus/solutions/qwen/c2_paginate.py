def paginate(data: list, page: int, per_page: int) -> list:
    """Return the slice of `data` for 1-indexed `page` with `per_page` items each.

    page 1 = first per_page items; a page past the end returns [].
    """
    if page < 1 or per_page < 1:
        return []
    start = (page - 1) * per_page
    return data[start:start + per_page]
