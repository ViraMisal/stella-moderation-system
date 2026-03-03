"""Тесты моделей SQLAlchemy (CRUD, методы моделей)."""
import datetime


class TestUserModel:
    def test_create_and_read(self, db_session):
        from core.models import User
        u = User(id=900001, username="test_user", first_name="Иван", last_name="Петров")
        db_session.add(u)
        db_session.flush()

        found = db_session.query(User).filter_by(id=900001).first()
        assert found is not None
        assert found.username == "test_user"
        assert found.first_name == "Иван"

    def test_display_name_with_username(self, db_session):
        from core.models import User
        u = User(id=900002, username="johndoe", first_name="John")
        db_session.add(u)
        db_session.flush()
        assert u.display_name() == "@johndoe"

    def test_display_name_with_names_no_username(self, db_session):
        from core.models import User
        u = User(id=900003, username=None, first_name="Анна", last_name="Иванова")
        db_session.add(u)
        db_session.flush()
        assert u.display_name() == "Анна Иванова"

    def test_display_name_fallback_to_id(self, db_session):
        from core.models import User
        u = User(id=900004, username=None, first_name=None, last_name=None)
        db_session.add(u)
        db_session.flush()
        assert u.display_name() == "900004"

    def test_blacklist_fields(self, db_session):
        from core.models import User
        u = User(id=900005, is_blacklisted=True, blacklist_reason="спам")
        db_session.add(u)
        db_session.flush()

        found = db_session.query(User).filter_by(id=900005).first()
        assert found.is_blacklisted is True
        assert found.blacklist_reason == "спам"

    def test_defaults(self, db_session):
        from core.models import User
        u = User(id=900006)
        db_session.add(u)
        db_session.flush()
        assert u.is_blacklisted is False
        assert u.is_web_admin is False
        assert u.message_count == 0


class TestPunishmentModel:
    def test_create_punishment(self, db_session):
        from core.models import Chat, Punishment, User
        user = User(id=910001)
        chat = Chat(id=910001, title="Тест-чат")
        db_session.add_all([user, chat])
        db_session.flush()

        p = Punishment(
            user_id=910001, chat_id=910001,
            type="mute", reason="флуд", active=True,
        )
        db_session.add(p)
        db_session.flush()

        found = db_session.query(Punishment).filter_by(user_id=910001).first()
        assert found is not None
        assert found.type == "mute"
        assert found.active is True

    def test_type_display_known_types(self):
        from core.models import Punishment
        cases = {
            "mute": "Мут",
            "ban": "Бан",
            "kick": "Кик",
            "warn": "Предупреждение",
            "mutemedia": "Медиамут",
            "unmute": "Снятие мута",
            "unban": "Разбан",
        }
        for ptype, expected in cases.items():
            p = Punishment(type=ptype)
            assert p.type_display() == expected, f"type={ptype!r}"

    def test_type_display_unknown(self):
        from core.models import Punishment
        p = Punishment(type="unknown_type")
        assert p.type_display() == "unknown_type"

    def test_type_display_none(self):
        from core.models import Punishment
        p = Punishment(type=None)
        assert p.type_display() == "-"

    def test_deactivate_punishment(self, db_session):
        from core.models import Chat, Punishment, User
        user = User(id=910002)
        chat = Chat(id=910002, title="Тест-чат2")
        db_session.add_all([user, chat])
        db_session.flush()

        p = Punishment(user_id=910002, chat_id=910002, type="ban", active=True)
        db_session.add(p)
        db_session.flush()

        p.active = False
        p.removed_at = datetime.datetime.utcnow()
        db_session.flush()

        assert p.active is False
        assert p.removed_at is not None


class TestSettingsModel:
    def test_get_default(self, db_session):
        from core.models import Settings
        val = Settings.get(db_session, "nonexistent_key_xyz", default="fallback")
        assert val == "fallback"

    def test_get_none_default(self, db_session):
        from core.models import Settings
        assert Settings.get(db_session, "nonexistent_key_abc") is None

    def test_set_and_get(self, db_session):
        from core.models import Settings
        # flush без commit чтобы откат изолировал тест
        key = "test_setting_unique_001"
        row = Settings(key=key, value="hello")
        db_session.add(row)
        db_session.flush()

        val = Settings.get(db_session, key)
        assert val == "hello"

    def test_update_existing(self, db_session):
        from core.models import Settings
        key = "test_setting_unique_002"
        row = Settings(key=key, value="first")
        db_session.add(row)
        db_session.flush()

        row.value = "second"
        db_session.flush()

        assert Settings.get(db_session, key) == "second"


class TestAIConversation:
    def test_empty_messages(self):
        from core.models import AIConversation
        conv = AIConversation()
        assert conv.get_messages() == []

    def test_set_and_get_messages(self):
        from core.models import AIConversation
        conv = AIConversation()
        msgs = [{"role": "user", "content": "Привет"}, {"role": "assistant", "content": "Здравствуй"}]
        conv.set_messages(msgs)
        assert conv.get_messages() == msgs

    def test_context_alias(self):
        """Алиас get_context/set_context."""
        from core.models import AIConversation
        conv = AIConversation()
        msgs = [{"role": "user", "content": "Test"}]
        conv.set_context(msgs)
        assert conv.get_context() == msgs

    def test_corrupted_json_returns_empty(self):
        from core.models import AIConversation
        conv = AIConversation(messages_json="not json at all {{")
        assert conv.get_messages() == []

    def test_non_list_json_returns_empty(self):
        from core.models import AIConversation
        conv = AIConversation(messages_json='{"role": "user"}')
        assert conv.get_messages() == []
