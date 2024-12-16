import pytest

from template.domain.models.category import Category


class TestCategory:
    def test_default_categories(self):
        """
        GIVEN the Category class
        WHEN getting all categories
        THEN it should return the default set of categories
        """
        categories = Category.get_categories()
        assert "comida" in categories
        assert "auto" in categories
        assert "casa" in categories
        assert "entretenimiento" in categories
        assert "compras" in categories
        assert "otros" in categories

    def test_add_new_category(self):
        """
        GIVEN a new category name
        WHEN adding it to the categories
        THEN it should be included in the set
        """
        Category.add_category("utilities")
        assert "utilities" in Category.get_categories()

    def test_case_insensitive_validation(self):
        """
        GIVEN a category name in different cases
        WHEN validating the category
        THEN it should validate regardless of case
        """
        assert Category.is_valid_category("COMIDA")
        assert Category.is_valid_category("comida")
        assert Category.is_valid_category("Comida")

    def test_invalid_category(self):
        """
        GIVEN an invalid category name
        WHEN validating the category
        THEN it should return False
        """
        assert not Category.is_valid_category("invalid_category")
