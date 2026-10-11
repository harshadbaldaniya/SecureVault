from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """25 per page by default; clients may ask for up to 100 (e.g. to fill a dropdown)."""

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100
