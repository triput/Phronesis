# ==============================================================================
# File: phronesis_django/wsgi.py
# Description: WSGI config for phronesis_django project
# Component: Core / WSGI Config
# Version: 1.0 (Gold Master)
# Created: 2026-06-30
# Last Update: 2026-06-30
# ==============================================================================
"""
WSGI config for phronesis_django project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os
import sys

# Swap standard sqlite3 with pysqlite3-binary if installed
try:
    import pysqlite3
    import pysqlite3.dbapi2
    
    # Ensure SQLITE_LIMIT_VARIABLE_NUMBER is defined on both namespaces
    for mod in (pysqlite3, pysqlite3.dbapi2):
        if not hasattr(mod, 'SQLITE_LIMIT_VARIABLE_NUMBER'):
            mod.SQLITE_LIMIT_VARIABLE_NUMBER = 9
            
    # Patch Connection to support getlimit
    if not hasattr(pysqlite3.dbapi2.Connection, 'getlimit'):
        class PatchedConnection(pysqlite3.dbapi2.Connection):
            def getlimit(self, limit):
                return 999
        
        # Keep reference to the original Connection
        org_Connection = pysqlite3.dbapi2.Connection
        
        # Override the Connection class in both namespaces
        pysqlite3.Connection = PatchedConnection
        pysqlite3.dbapi2.Connection = PatchedConnection
        
        # Override connect in both namespaces to inject PatchedConnection factory
        org_connect = pysqlite3.dbapi2.connect
        def patched_connect(*args, **kwargs):
            factory = kwargs.get('factory')
            if factory is None or factory == org_Connection:
                kwargs['factory'] = PatchedConnection
            return org_connect(*args, **kwargs)
            
        pysqlite3.connect = patched_connect
        pysqlite3.dbapi2.connect = patched_connect
        
    sys.modules['sqlite3'] = pysqlite3
    sys.modules['sqlite3.dbapi2'] = pysqlite3.dbapi2
except ImportError:
    pass

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "phronesis_django.settings")

application = get_wsgi_application()

