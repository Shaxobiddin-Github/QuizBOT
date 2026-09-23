from . import group, menu, setup, classic, pro, library  # noqa: F401

ROUTERS = [group.router, menu.router, setup.router,
           classic.router, pro.router, library.router]
