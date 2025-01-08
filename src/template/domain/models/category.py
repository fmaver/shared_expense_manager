"""Module for managing expense categories."""

from typing import Set


class Category:
    _categories: Set[str] = {
        "auto",
        "casa",
        "salidas",
        "compras",
        "mascota",
        "entretenimiento",
        "prestamo",
        "shopping",
        "balance",
        "otros",
    }

    @classmethod
    def add_category(cls, name: str) -> None:
        """Add a new category to the set of valid categories.

        Args:
            name: The name of the category to add
        """
        cls._categories.add(name.lower())

    @classmethod
    def get_categories(cls) -> Set[str]:
        """Return a copy of all valid categories.

        Returns:
            A set of all valid category names
        """
        return cls._categories.copy()

    @classmethod
    def get_all_categories(cls) -> Set[str]:
        """Get all available categories."""
        return cls._categories

    @classmethod
    def is_valid_category(cls, category: str) -> bool:
        """Check if a category name is valid.

        Args:
            category: The category name to check

        Returns:
            True if the category is valid, False otherwise
        """
        return category.lower() in cls._categories
