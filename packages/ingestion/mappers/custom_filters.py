"""Custom filter loader — safely compiles user-provided Python filter functions.

User-defined Jinja2 filters are stored as ``_JinjaFilter`` nodes in the graph
database.  This module validates the source code (via AST inspection) and
compiles it into callable functions that can be registered with the
Jinja2MappingEngine.

Security model:
* Source is parsed with ``ast`` and walked to reject imports, dunder access,
  and calls to a blocklist of dangerous names.
* Compilation and execution happen in a restricted namespace with
  ``__builtins__`` stripped out.
"""

from __future__ import annotations

import ast
import types
from typing import Any, Callable

import structlog

logger = structlog.get_logger()

# Names that MUST NOT appear as function calls or attribute references in
# user-supplied filter source.  This is a defence-in-depth measure on top of
# the AST-level import/dunder rejection.
BLOCKED_NAMES: frozenset[str] = frozenset(
    {
        "import",
        "__import__",
        "exec",
        "eval",
        "compile",
        "open",
        "os",
        "sys",
        "subprocess",
        "shutil",
        "pathlib",
        "glob",
        "__builtins__",
        "breakpoint",
        "exit",
        "quit",
    }
)


class CustomFilterLoader:
    """Load and validate user-provided Python filter functions."""

    # Expose at class level so callers can inspect without instantiation.
    BLOCKED_NAMES = BLOCKED_NAMES

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def validate_filter_source(source: str) -> list[str]:
        """Validate Python source code for safety.

        Returns a list of error strings.  An empty list means the source is
        considered safe enough to compile.

        Rules enforced:
        1. The source must parse as valid Python.
        2. The module body must contain exactly one ``FunctionDef`` (no classes,
           no top-level expressions beyond the function).
        3. No ``Import`` or ``ImportFrom`` nodes anywhere in the AST.
        4. No attribute access on dunder names (``__foo``).
        5. No calls to names in ``BLOCKED_NAMES``.
        """
        errors: list[str] = []

        # --- 1. Parse ---
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            errors.append(f"Syntax error: {exc}")
            return errors

        # --- 2. Exactly one function definition at top level ---
        func_defs = [
            node for node in tree.body if isinstance(node, ast.FunctionDef)
        ]
        non_func = [
            node
            for node in tree.body
            if not isinstance(node, (ast.FunctionDef, ast.Expr))
            # Allow bare docstrings (ast.Expr with ast.Constant/Str)
            or (
                isinstance(node, ast.Expr)
                and not isinstance(node.value, ast.Constant)
            )
        ]

        if len(func_defs) == 0:
            errors.append("Source must define exactly one function; found none.")
        elif len(func_defs) > 1:
            errors.append(
                f"Source must define exactly one function; found {len(func_defs)}."
            )

        if non_func:
            errors.append(
                "Source must only contain a single function definition "
                "(no top-level statements, classes, or assignments)."
            )

        # --- 3-5. Walk the full AST ---
        for node in ast.walk(tree):
            # 3. Reject imports
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                errors.append(
                    f"Imports are not allowed (line {getattr(node, 'lineno', '?')})."
                )

            # 4. Reject dunder attribute access
            if isinstance(node, ast.Attribute):
                if node.attr.startswith("__"):
                    errors.append(
                        f"Dunder attribute access '{node.attr}' is not allowed "
                        f"(line {getattr(node, 'lineno', '?')})."
                    )

            # 5. Reject blocked-name calls
            if isinstance(node, ast.Call):
                func_node = node.func
                called_name: str | None = None
                if isinstance(func_node, ast.Name):
                    called_name = func_node.id
                elif isinstance(func_node, ast.Attribute):
                    called_name = func_node.attr

                if called_name and called_name in BLOCKED_NAMES:
                    errors.append(
                        f"Call to blocked name '{called_name}' is not allowed "
                        f"(line {getattr(node, 'lineno', '?')})."
                    )

            # Also check bare Name references to blocked names (e.g., passing
            # ``eval`` as a value rather than calling it).
            if isinstance(node, ast.Name) and node.id in BLOCKED_NAMES:
                errors.append(
                    f"Reference to blocked name '{node.id}' is not allowed "
                    f"(line {getattr(node, 'lineno', '?')})."
                )

        return errors

    # ------------------------------------------------------------------
    # Compilation
    # ------------------------------------------------------------------

    @staticmethod
    def load_from_source(name: str, python_source: str) -> Callable:
        """Compile user-provided source and extract the named function.

        Args:
            name: Expected function name to extract after execution.
            python_source: Raw Python source defining exactly one function.

        Returns:
            The compiled callable.

        Raises:
            ValueError: If validation fails or the function cannot be found.
        """
        errors = CustomFilterLoader.validate_filter_source(python_source)
        if errors:
            raise ValueError(
                f"Filter '{name}' failed validation:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        code = compile(python_source, f"<filter:{name}>", "exec")

        # Execute in a restricted namespace — no builtins available.
        namespace: dict[str, Any] = {"__builtins__": {}}
        exec(code, namespace)  # noqa: S102 — intentionally restricted exec

        func = namespace.get(name)
        if func is None or not isinstance(func, types.FunctionType):
            raise ValueError(
                f"Filter source for '{name}' did not define a function named '{name}'."
            )

        return func

    # ------------------------------------------------------------------
    # Database loading
    # ------------------------------------------------------------------

    @staticmethod
    async def load_filters_from_db(driver: Any) -> dict[str, Callable]:
        """Load all active ``_JinjaFilter`` nodes from Neo4j and compile them.

        Each ``_JinjaFilter`` node is expected to have:
        * ``name`` — the filter name to register in Jinja2.
        * ``source`` — Python source code defining the function.
        * ``active`` — boolean flag; only active filters are loaded.

        Args:
            driver: An async Neo4j driver instance.

        Returns:
            A dict mapping filter name to compiled callable.
        """
        filters: dict[str, Callable] = {}

        query = (
            "MATCH (f:_JinjaFilter) "
            "WHERE f.active = true "
            "RETURN f.name AS name, f.source AS source"
        )

        async with driver.session() as session:
            result = await session.run(query)
            records = [record async for record in result]

        for record in records:
            name = record["name"]
            source = record["source"]

            try:
                func = CustomFilterLoader.load_from_source(name, source)
                filters[name] = func
                logger.info("custom_filter_loaded", filter_name=name)
            except ValueError as exc:
                logger.warning(
                    "custom_filter_rejected",
                    filter_name=name,
                    reason=str(exc),
                )

        return filters
