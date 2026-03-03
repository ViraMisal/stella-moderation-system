"""Общие фикстуры для тестов Stella."""
import os

import pytest

# Подменяем переменные окружения до импорта приложения,
# чтобы не нужен был реальный .env файл.
os.environ.setdefault("BOT_TOKEN", "123456789:AABBCCDDEEFFaabbccddeeff-1234567890")
os.environ.setdefault("FLASK_SECRET", "test-secret-key-for-tests-only")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "testpass")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENV", "testing")


@pytest.fixture(scope="session")
def db_engine():
    """Движок SQLite in-memory — создаём таблицы один раз на всю сессию тестов."""
    from core.models import Base, engine
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture()
def db_session(db_engine):
    """Сессия БД с откатом после каждого теста — изоляция данных."""
    from core.models import SessionLocal
    db = SessionLocal()
    yield db
    db.rollback()
    db.close()


@pytest.fixture(scope="session")
def flask_app():
    """Flask-приложение в тестовом режиме."""
    from web import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


@pytest.fixture()
def client(flask_app):
    """Тест-клиент Flask."""
    with flask_app.test_client() as c:
        yield c


@pytest.fixture()
def auth_client(flask_app):
    """Тест-клиент с активной сессией супер-админа."""
    with flask_app.test_client() as c:
        with c.session_transaction() as sess:
            sess["admin"] = True
            sess["role"] = "superadmin"
            sess["who"] = "test_admin"
            sess["admin_id"] = None
            sess["admin_chats"] = []
        yield c
