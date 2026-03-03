"""Тесты Flask-маршрутов (интеграционные)."""
import pytest


class TestHealthEndpoint:
    def test_health_returns_json(self, client):
        resp = client.get("/health")
        assert resp.status_code in (200, 503)
        data = resp.get_json()
        assert "status" in data
        assert "db" in data

    def test_health_status_ok_or_degraded(self, client):
        resp = client.get("/health")
        data = resp.get_json()
        assert data["status"] in ("ok", "degraded")

    def test_metrics_no_auth_required(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "users" in data
        assert "punishments" in data


class TestAuthRoutes:
    def test_login_get_returns_200(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_login_bad_credentials_stays_on_page(self, client):
        resp = client.post("/login", data={"username": "wrong", "password": "wrong"})
        # Неверные данные → рендерим login.html заново (200) либо redirect (3xx)
        # В любом случае не должны попасть на dashboard.
        assert resp.status_code in (200, 302)
        if resp.status_code == 302:
            assert "/login" in resp.headers.get("Location", "")

    def test_login_correct_credentials_redirects_to_dashboard(self, client):
        # conftest устанавливает ADMIN_USERNAME=admin, ADMIN_PASSWORD=testpass
        resp = client.post(
            "/login",
            data={"username": "admin", "password": "testpass"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "dashboard" in resp.headers.get("Location", "")

    def test_logout_redirects_to_login(self, client):
        resp = client.get("/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "login" in resp.headers.get("Location", "")


class TestProtectedRoutes:
    def test_dashboard_requires_login(self, client):
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 302
        assert "login" in resp.headers.get("Location", "")

    def test_users_list_requires_login(self, client):
        resp = client.get("/users", follow_redirects=False)
        assert resp.status_code == 302
        assert "login" in resp.headers.get("Location", "")

    def test_appeals_requires_login(self, client):
        resp = client.get("/appeals", follow_redirects=False)
        assert resp.status_code == 302
        assert "login" in resp.headers.get("Location", "")

    def test_logs_requires_login(self, client):
        resp = client.get("/logs", follow_redirects=False)
        assert resp.status_code == 302
        assert "login" in resp.headers.get("Location", "")


class TestAuthenticatedRoutes:
    def test_dashboard_with_auth_returns_200(self, auth_client):
        resp = auth_client.get("/dashboard")
        assert resp.status_code == 200

    def test_users_list_with_auth_returns_200(self, auth_client):
        resp = auth_client.get("/users")
        assert resp.status_code == 200

    def test_users_search_with_auth(self, auth_client):
        resp = auth_client.get("/users?q=test")
        assert resp.status_code == 200

    def test_api_stats_with_auth(self, auth_client):
        resp = auth_client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_users" in data
        assert "total_punishments" in data

    def test_logs_with_auth_returns_200(self, auth_client):
        resp = auth_client.get("/logs")
        assert resp.status_code == 200

    def test_bot_send_superadmin_required(self, auth_client):
        # auth_client имеет role=superadmin, должен пройти
        resp = auth_client.get("/bot/send")
        assert resp.status_code == 200
