"""
Ruqqus test suite.

Marks this directory as a package so test modules can share helpers via
``from tests.conftest import ...`` regardless of the working directory pytest
was started from.  ``pytest.ini`` puts the project root on ``sys.path``.

See ``tests/conftest.py`` for how the test database is chosen and reset.
"""
