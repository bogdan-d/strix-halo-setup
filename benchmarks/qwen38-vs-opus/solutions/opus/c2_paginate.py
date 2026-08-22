# implement paginate(data, page, per_page) below
def paginate(data: list, page: int, per_page: int) -> list:
    start = (page - 1) * per_page
    end = start + per_page
    return data[start:end]
