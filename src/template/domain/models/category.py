"""Module for managing expense categories."""

from typing import Dict, List, Optional, Set, Tuple


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

    # Emoji mapping for each category
    _category_emojis: Dict[str, str] = {
        "auto": "🚙",
        "casa": "🏠",
        "salidas": "🍽️",
        "compras": "🛒",
        "mascota": "🐾",
        "entretenimiento": "🎮",
        "prestamo": "💰",
        "shopping": "🛍️",
        "balance": "💵",
        "otros": "📦",
    }

    @classmethod
    def add_category(cls, name: str, emoji: Optional[str] = None) -> None:
        """Add a new category to the list of valid categories.

        Args:
            name: The name of the category to add
            emoji: Optional emoji for the category
        """
        name = name.lower()
        if name not in cls._categories:
            cls._categories.append(name)
            if emoji:
                cls._category_emojis[name] = emoji

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
        """Return a list of tuples containing category numbers and names.

        Args:
            include_internal: Whether to include internal categories

        Returns:
            List[Tuple[int, str]]: List of tuples (number, category_name)
        """
        categories = cls._categories if include_internal else cls.get_user_categories()
        return list(enumerate(categories, start=1))

    @classmethod
    def get_numbered_categories_with_emoji(cls, include_internal: bool = False) -> List[Tuple[int, str, str]]:
        """Return a list of tuples containing category numbers, names, and emojis.

        Args:
            include_internal: Whether to include internal categories

        Returns:
            List[Tuple[int, str, str]]: List of tuples (number, category_name, emoji)
        """
        categories = cls._categories if include_internal else cls.get_user_categories()
        return [(i, cat, cls._category_emojis.get(cat, "")) for i, cat in enumerate(categories, start=1)]

    @classmethod
    def get_category_by_number(cls, number: int, include_internal: bool = False) -> Optional[str]:
        """Get a category name by its number.

        Args:
            number: The category number (1-based)
            include_internal: Whether to include internal categories

        Returns:
            Optional[str]: The category name, or None if not found
        """
        categories = cls._categories if include_internal else cls.get_user_categories()
        if 1 <= number <= len(categories):
            return categories[number - 1]
        return None

    @classmethod
    def get_category_emoji(cls, category: str) -> str:
        """Get the emoji for a category.

        Args:
            category: The category name

        Returns:
            str: The emoji for the category, or empty string if not found
        """
        return cls._category_emojis.get(category.lower(), "")

    @classmethod
    def is_valid_category(cls, category: str) -> bool:
        """Check if a category is valid.

        Args:
            category: The name of the category to check

        Returns:
            bool: True if the category is valid, False otherwise
        """
        return category.lower() in cls._categories
