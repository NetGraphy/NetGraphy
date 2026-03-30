"""Tests for custom filter loader (packages/ingestion/mappers/custom_filters.py)."""

import pytest

from packages.ingestion.mappers.custom_filters import CustomFilterLoader


# ---------------------------------------------------------------------------
# validate_filter_source
# ---------------------------------------------------------------------------

class TestValidateFilterSource:
    def test_valid_single_function(self):
        source = """
def double(value):
    return value * 2
"""
        errors = CustomFilterLoader.validate_filter_source(source)
        assert errors == []

    def test_valid_function_with_docstring(self):
        source = '''
def greet(name):
    """Return a greeting."""
    return "Hello, " + name
'''
        errors = CustomFilterLoader.validate_filter_source(source)
        assert errors == []

    def test_rejects_imports(self):
        source = """
import os
def bad(x):
    return os.path.join(x, "y")
"""
        errors = CustomFilterLoader.validate_filter_source(source)
        assert any("Import" in e or "import" in e.lower() for e in errors)

    def test_rejects_from_import(self):
        source = """
from pathlib import Path
def bad(x):
    return str(Path(x))
"""
        errors = CustomFilterLoader.validate_filter_source(source)
        assert any("Import" in e or "import" in e.lower() for e in errors)

    def test_rejects_multiple_functions(self):
        source = """
def one(x):
    return x
def two(x):
    return x
"""
        errors = CustomFilterLoader.validate_filter_source(source)
        assert any("exactly one function" in e.lower() for e in errors)

    def test_rejects_no_function(self):
        source = """
x = 42
"""
        errors = CustomFilterLoader.validate_filter_source(source)
        assert any("exactly one function" in e.lower() for e in errors)

    def test_rejects_dunder_attribute_access(self):
        source = """
def bad(x):
    return x.__class__
"""
        errors = CustomFilterLoader.validate_filter_source(source)
        assert any("__class__" in e for e in errors)

    def test_rejects_eval_call(self):
        source = """
def bad(x):
    return eval(x)
"""
        errors = CustomFilterLoader.validate_filter_source(source)
        assert any("eval" in e for e in errors)

    def test_rejects_exec_call(self):
        source = """
def bad(x):
    exec(x)
    return x
"""
        errors = CustomFilterLoader.validate_filter_source(source)
        assert any("exec" in e for e in errors)

    def test_rejects_open_call(self):
        source = """
def bad(x):
    return open(x).read()
"""
        errors = CustomFilterLoader.validate_filter_source(source)
        assert any("open" in e for e in errors)

    def test_rejects_blocked_name_reference(self):
        source = """
def bad(x):
    f = eval
    return f(x)
"""
        errors = CustomFilterLoader.validate_filter_source(source)
        assert any("eval" in e for e in errors)

    def test_rejects_syntax_error(self):
        source = """
def bad(x
    return x
"""
        errors = CustomFilterLoader.validate_filter_source(source)
        assert any("syntax" in e.lower() for e in errors)

    def test_rejects_top_level_assignment(self):
        source = """
CONSTANT = 42
def my_func(x):
    return x + CONSTANT
"""
        errors = CustomFilterLoader.validate_filter_source(source)
        assert any("single function definition" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# load_from_source
# ---------------------------------------------------------------------------

class TestLoadFromSource:
    def test_loads_valid_function(self):
        source = """
def double(value):
    return value * 2
"""
        func = CustomFilterLoader.load_from_source("double", source)
        assert callable(func)
        assert func(5) == 10

    def test_string_manipulation_filter(self):
        source = """
def upper_first(value):
    if not value:
        return value
    return value[0].upper() + value[1:]
"""
        func = CustomFilterLoader.load_from_source("upper_first", source)
        assert func("hello") == "Hello"
        assert func("") == ""

    def test_raises_on_validation_failure(self):
        source = """
import os
def bad(x):
    return x
"""
        with pytest.raises(ValueError, match="failed validation"):
            CustomFilterLoader.load_from_source("bad", source)

    def test_raises_on_wrong_function_name(self):
        source = """
def actual_name(x):
    return x
"""
        with pytest.raises(ValueError, match="did not define a function named 'expected_name'"):
            CustomFilterLoader.load_from_source("expected_name", source)

    def test_no_builtins_available(self):
        """Functions compiled from user source should not have access to builtins."""
        source = """
def try_print(x):
    print(x)
    return x
"""
        # This should load fine (print is not in BLOCKED_NAMES),
        # but calling it will fail because __builtins__ is empty.
        func = CustomFilterLoader.load_from_source("try_print", source)
        with pytest.raises(NameError):
            func("test")


# ---------------------------------------------------------------------------
# BLOCKED_NAMES
# ---------------------------------------------------------------------------

class TestBlockedNames:
    def test_blocked_names_is_frozenset(self):
        assert isinstance(CustomFilterLoader.BLOCKED_NAMES, frozenset)

    def test_key_dangerous_names_are_blocked(self):
        for name in ["eval", "exec", "open", "os", "sys", "subprocess", "__import__"]:
            assert name in CustomFilterLoader.BLOCKED_NAMES
