from . import admin, group, menu, setup, iq, classic, pro, library  # noqa: F401

ROUTERS = [admin.router, group.router, menu.router, setup.router,
           iq.router, classic.router, pro.router, library.router]
