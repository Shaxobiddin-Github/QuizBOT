from . import admin, group, menu, setup, classic, pro, library  # noqa: F401

ROUTERS = [admin.router, group.router, menu.router, setup.router,
           classic.router, pro.router, library.router]
