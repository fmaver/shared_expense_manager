"""Every notification dispatched from an endpoint must be handed a push service.

This exists because the same defect shipped three times: a notify_* method grew a push branch
while its caller kept the old argument list. Nothing failed — the push code was simply never
reached, and members whose notification_preference is still the NONE column default silently
received nothing at all. Unit tests could not catch it, because each half was correct.

The check reads the source rather than the behaviour on purpose: the bug is an *absence* at a
call site, and there is no runtime moment where an absent argument announces itself.
"""

import ast
import pathlib

import pytest

ENTRYPOINTS = pathlib.Path(__file__).resolve().parents[2].parent / "src" / "template" / "entrypoint"

# Notifications that deliberately reach nobody who could hold a push subscription.
EXEMPT: set[str] = set()


def _dispatch_sites():
    """Every `NotificationService().notify_*` call in the routers, with its keywords."""
    for path in sorted(ENTRYPOINTS.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for arg in [*node.args, *(kw.value for kw in node.keywords)]:
                # Background tasks pass the bound method itself, uncalled.
                if isinstance(arg, ast.Attribute) and arg.attr.startswith("notify_"):
                    keywords = {kw.arg for kw in node.keywords}
                    yield path.name, node.lineno, arg.attr, keywords
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr.startswith("notify_"):
                yield path.name, node.lineno, func.attr, {kw.arg for kw in node.keywords}


def test_the_scan_actually_finds_call_sites():
    """A guard that silently matches nothing would pass forever."""
    assert len(list(_dispatch_sites())) >= 5


@pytest.mark.parametrize("site", list(_dispatch_sites()), ids=lambda s: f"{s[0]}:{s[1]}:{s[2]}")
def test_every_notification_is_given_a_push_service(site):
    filename, lineno, method, keywords = site
    if method in EXEMPT:
        pytest.skip(f"{method} is exempt")
    assert "push_service" in keywords, (
        f"{filename}:{lineno} calls {method} without push_service. Members with the app "
        f"installed will fall back to email, or to nothing when their preference is NONE."
    )
