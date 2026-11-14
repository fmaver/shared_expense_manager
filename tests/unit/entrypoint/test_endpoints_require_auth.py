"""Every group-scoped route must require authentication.

Four routes were reachable without a token — `GET /shares/{year}/{month}`,
`POST /shares/recalculate/{year}/{month}`, `GET /expenses/{id}` and
`GET /expenses/{id}/parent` — while every sibling route beside them had a guard. Anyone who
knew a group id could read a group's expenses and balances, and recalculate them.

This test inspects the registered routes rather than calling them, so it needs no database and
fails the moment a new group-scoped endpoint is added without a guard.
"""

import inspect

from template.service_layer.auth_service import get_current_member
from template.service_layer.shortcut_token_service import get_shortcut_member

# Routes that are public by design.
PUBLIC_PREFIXES = (
    "/api/v1/auth",
    "/api/v1/invitations",
    "/api/v1/join",
    "/api/v1/categories",  # a static list, no user data
    "/api/v1/currency",  # a public exchange rate
    # No lleva JWT porque no hay un usuario detrás de un cron. Lo protege el header
    # X-Task-Secret, y sin TASK_SECRET configurado responde 404 en vez de quedar abierto.
    "/api/v1/tasks",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/webhook",
    "/liveness",
    "/readiness",
)

# The iOS shortcut authenticates with its personal token instead of a JWT, and only here.
SHORTCUT_PREFIX = "/api/v1/quick-capture"


def _depends_on(endpoint, *guards) -> bool:
    """True if any parameter of the endpoint resolves through one of `guards`."""
    for param in inspect.signature(endpoint).parameters.values():
        dependency = getattr(param.default, "dependency", None)
        if dependency in guards:
            return True
    return False


def _depends_on_current_member(endpoint) -> bool:
    """True if any parameter of the endpoint resolves through get_current_member."""
    return _depends_on(endpoint, get_current_member)


def test_every_group_scoped_route_requires_authentication(test_client):
    """A route under /groups/{group_id} exposes one group's data and must be guarded."""
    unguarded = []
    for route in test_client.app.routes:
        path = getattr(route, "path", "")
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None or not path.startswith("/api/v1/groups"):
            continue
        if not _depends_on_current_member(endpoint):
            unguarded.append(f"{sorted(route.methods)[0]} {path}")

    assert unguarded == [], f"group-scoped routes without auth: {unguarded}"


def test_no_unexpected_public_routes(test_client):
    """Catch a new unguarded route anywhere, not just under /groups.

    Anything genuinely public belongs in PUBLIC_PREFIXES with a reason, so the decision is
    recorded rather than inferred from a missing dependency.
    """
    unguarded = []
    for route in test_client.app.routes:
        path = getattr(route, "path", "")
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None or path.startswith(PUBLIC_PREFIXES) or path in ("/", ""):
            continue
        guards = (get_shortcut_member,) if path.startswith(SHORTCUT_PREFIX) else (get_current_member,)
        if not _depends_on(endpoint, *guards):
            unguarded.append(f"{sorted(route.methods)[0]} {path}")

    assert unguarded == [], f"unexpected unguarded routes: {unguarded}"


def test_shortcut_token_is_accepted_only_under_quick_capture(test_client):
    """The shortcut token never opens a route outside its prefix, and those routes take no JWT.

    The token lives in a phone's shortcut and cannot expire, so what it can reach is kept to
    the capture flow on purpose.
    """
    leaked, mixed = [], []
    for route in test_client.app.routes:
        path = getattr(route, "path", "")
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        name = f"{sorted(route.methods)[0]} {path}"
        if path.startswith(SHORTCUT_PREFIX):
            if _depends_on(endpoint, get_current_member):
                mixed.append(name)
        elif _depends_on(endpoint, get_shortcut_member):
            leaked.append(name)

    assert leaked == [], f"routes outside {SHORTCUT_PREFIX} accepting the shortcut token: {leaked}"
    assert mixed == [], f"quick-capture routes depending on the JWT login: {mixed}"
