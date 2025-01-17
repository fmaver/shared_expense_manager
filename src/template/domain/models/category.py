"""Module for managing expense categories."""

from typing import List, Optional, Set, Tuple


class Category:
    _categories: List[str] = [
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
    ]

    _internal_categories: Set[str] = {"balance", "prestamo"}

    @classmethod
    def add_category(cls, name: str) -> None:
        """Add a new category to the list of valid categories.

        Args:
            name: The name of the category to add
        """
        if name.lower() not in cls._categories:
            cls._categories.append(name.lower())

    @classmethod
    def get_categories(cls) -> List[str]:
        """Return a copy of all valid categories.

        Returns:
            List[str]: List of all valid categories
        """
        return cls._categories.copy()

    @classmethod
    def get_user_categories(cls) -> List[str]:
        """Return a copy of categories that should be shown to users.

        Returns:
            List[str]: List of user-facing categories
        """
        return [cat for cat in cls._categories if cat not in cls._internal_categories]

    @classmethod
    def get_numbered_categories(cls, include_internal: bool = False) -> List[Tuple[int, str]]:
        """Return all categories with their corresponding numbers.

        Args:
            include_internal: Whether to include internal categories like 'balance' and 'prestamo'

        Returns:
            List[Tuple[int, str]]: List of tuples containing (number, category_name)
        """
        categories = cls._categories if include_internal else cls.get_user_categories()
        return [(i + 1, cat) for i, cat in enumerate(categories)]

    @classmethod
    def get_category_by_number(cls, number: int, include_internal: bool = False) -> Optional[str]:
        """Get a category name by its number.

        Args:
            number: The number of the category (1-based index)
            include_internal: Whether to include internal categories in the numbering

        Returns:
            Optional[str]: The category name if found, None otherwise
        """
        categories = cls._categories if include_internal else cls.get_user_categories()
        try:
            return categories[number - 1]
        except IndexError:
            return None

    @classmethod
    def get_category_number(cls, category: str, include_internal: bool = False) -> Optional[int]:
        """Get the number for a given category name.

        Args:
            category: The name of the category
            include_internal: Whether to include internal categories in the numbering

        Returns:
            Optional[int]: The category number (1-based index) if found, None otherwise
        """
        categories = cls._categories if include_internal else cls.get_user_categories()
        try:
            return categories.index(category.lower()) + 1
        except ValueError:
            return None

    @classmethod
    def is_valid_category(cls, category: str) -> bool:
        """Check if a category is valid.

        Args:
            category: The name of the category to check

        Returns:
            bool: True if the category is valid, False otherwise
        """
        return category.lower() in cls._categories
