"""
CampusLens API backend.

Supabase PostgreSQL only. Every request is authenticated against a Supabase
Auth JWT, and the request's role is derived from the verified token - never
from anything the client sent.
"""

__all__ = ["__version__"]

__version__ = "2.0.0"