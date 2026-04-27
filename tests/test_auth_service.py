from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_refresh_token, make_user


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    session.execute = AsyncMock()
    return session


@pytest.mark.asyncio
class TestPasswordHashing:
    def test_hash_password_returns_bcrypt_hash(self):
        from app.utils.security import hash_password
        hashed = hash_password("MyP@ssw0rd!")
        assert hashed.startswith("$2b$")

    def test_verify_password_correct(self):
        from app.utils.security import hash_password, verify_password
        hashed = hash_password("MyP@ssw0rd!")
        assert verify_password("MyP@ssw0rd!", hashed) is True

    def test_verify_password_wrong(self):
        from app.utils.security import hash_password, verify_password
        hashed = hash_password("MyP@ssw0rd!")
        assert verify_password("WrongPass1!", hashed) is False

    def test_verify_password_invalid_hash(self):
        from app.utils.security import verify_password
        assert verify_password("anything", "not-a-hash") is False


class TestPasswordStrengthValidator:
    def test_valid_password_passes(self):
        from app.schemas.auth import RegisterRequest
        req = RegisterRequest(
            email="a@b.com",
            password="Str0ng!Pass",
            first_name="A",
            last_name="B",
        )
        assert req.password == "Str0ng!Pass"

    def test_missing_uppercase_fails(self):
        from pydantic import ValidationError
        from app.schemas.auth import RegisterRequest
        with pytest.raises(ValidationError, match="uppercase"):
            RegisterRequest(email="a@b.com", password="str0ng!pass", first_name="A", last_name="B")

    def test_missing_lowercase_fails(self):
        from pydantic import ValidationError
        from app.schemas.auth import RegisterRequest
        with pytest.raises(ValidationError, match="lowercase"):
            RegisterRequest(email="a@b.com", password="STR0NG!PASS", first_name="A", last_name="B")

    def test_missing_digit_fails(self):
        from pydantic import ValidationError
        from app.schemas.auth import RegisterRequest
        with pytest.raises(ValidationError, match="digit"):
            RegisterRequest(email="a@b.com", password="Strong!Pass", first_name="A", last_name="B")

    def test_missing_special_char_fails(self):
        from pydantic import ValidationError
        from app.schemas.auth import RegisterRequest
        with pytest.raises(ValidationError, match="special"):
            RegisterRequest(email="a@b.com", password="Str0ngPass1", first_name="A", last_name="B")


@pytest.mark.asyncio
class TestTokenService:
    def setup_method(self):
        from app.services.token_service import TokenService
        self.svc = TokenService()

    def test_create_access_token_returns_string(self):
        user_id = str(uuid.uuid4())
        token, expires_at = self.svc.create_access_token(user_id)
        assert isinstance(token, str)
        assert expires_at > datetime.now(UTC)

    def test_create_access_token_with_tenant(self):
        user_id = str(uuid.uuid4())
        tenant_id = uuid.uuid4()
        token, _ = self.svc.create_access_token(user_id, tenant_id=tenant_id)
        payload = self.svc.decode_token(token, expected_type="access")
        assert payload.tenant_id == tenant_id

    def test_create_refresh_token_returns_string(self):
        user_id = str(uuid.uuid4())
        token, expires_at = self.svc.create_refresh_token(user_id)
        assert isinstance(token, str)
        assert expires_at > datetime.now(UTC)

    def test_decode_access_token(self):
        user_id = str(uuid.uuid4())
        token, _ = self.svc.create_access_token(user_id)
        payload = self.svc.decode_token(token, expected_type="access")
        assert str(payload.subject) == user_id
        assert payload.token_type == "access"

    def test_decode_token_wrong_type_raises(self):
        from app.utils.errors import AppError
        user_id = str(uuid.uuid4())
        token, _ = self.svc.create_access_token(user_id)
        with pytest.raises(AppError) as exc_info:
            self.svc.decode_token(token, expected_type="refresh")
        assert exc_info.value.code == "INVALID_TOKEN_TYPE"

    def test_decode_expired_token_raises(self):
        import jwt as pyjwt
        from app.utils.errors import AppError
        from app.config import get_settings
        settings = get_settings()
        expired_payload = {
            "sub": str(uuid.uuid4()),
            "type": "access",
            "exp": datetime.now(UTC) - timedelta(seconds=1),
        }
        token = pyjwt.encode(expired_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        with pytest.raises(AppError) as exc_info:
            self.svc.decode_token(token)
        assert exc_info.value.code == "TOKEN_EXPIRED"

    def test_decode_invalid_token_raises(self):
        from app.utils.errors import AppError
        with pytest.raises(AppError) as exc_info:
            self.svc.decode_token("not.a.valid.token")
        assert exc_info.value.code == "INVALID_TOKEN"

    def test_hash_token_is_deterministic(self):
        token = "some-token-value"
        assert self.svc.hash_token(token) == self.svc.hash_token(token)

    def test_hash_token_different_inputs_differ(self):
        assert self.svc.hash_token("token-a") != self.svc.hash_token("token-b")

    async def test_issue_token_pair(self, mock_session):
        user_id = uuid.uuid4()
        result = await self.svc.issue_token_pair(mock_session, user_id)
        assert result.access_token
        assert result.refresh_token
        assert result.token_type == "Bearer"
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()


@pytest.mark.asyncio
class TestAuthServiceRegister:
    async def test_register_new_user_succeeds(self, mock_session):
        from app.services.auth_service import AuthService
        from app.schemas.auth import RegisterRequest

        user = make_user(email="new@example.com")
        mock_session.scalar.return_value = None
        mock_session.refresh.side_effect = lambda obj, *a, **kw: None

        with patch("app.services.auth_service.send_email", new_callable=AsyncMock):
            with patch("app.services.auth_service.hash_password", return_value="hashed"):
                svc = AuthService(mock_session)
                svc.token_service.create_verification_token = MagicMock(
                    return_value=("tok", datetime.now(UTC) + timedelta(hours=24))
                )
                svc.token_service.hash_token = MagicMock(return_value="hashed_tok")
                payload = RegisterRequest(
                    email="new@example.com",
                    password="Str0ng!Pass",
                    first_name="New",
                    last_name="User",
                )
                result = await svc.register(payload)
                assert result is not None
                mock_session.commit.assert_called()

    async def test_register_duplicate_email_raises(self, mock_session):
        from app.services.auth_service import AuthService
        from app.schemas.auth import RegisterRequest
        from app.utils.errors import AppError

        existing_user = make_user(email="dup@example.com")
        mock_session.scalar.return_value = existing_user

        svc = AuthService(mock_session)
        payload = RegisterRequest(
            email="dup@example.com",
            password="Str0ng!Pass",
            first_name="A",
            last_name="B",
        )
        with pytest.raises(AppError) as exc_info:
            await svc.register(payload)
        assert exc_info.value.code == "EMAIL_ALREADY_EXISTS"


@pytest.mark.asyncio
class TestAuthServiceLogin:
    async def test_login_valid_credentials(self, mock_session):
        from app.services.auth_service import AuthService
        from app.schemas.auth import LoginRequest

        user = make_user(email="user@example.com", is_active=True)
        mock_session.scalar.return_value = user

        svc = AuthService(mock_session)
        svc.token_service.issue_token_pair = AsyncMock(
            return_value=MagicMock(access_token="acc", refresh_token="ref", token_type="Bearer", expires_in=900)
        )

        with patch("app.services.auth_service.verify_password", return_value=True):
            result = await svc.login(LoginRequest(email="user@example.com", password="Str0ng!Pass"))
        assert result.access_token == "acc"

    async def test_login_wrong_password_raises(self, mock_session):
        from app.services.auth_service import AuthService
        from app.schemas.auth import LoginRequest
        from app.utils.errors import AppError

        user = make_user()
        mock_session.scalar.return_value = user

        svc = AuthService(mock_session)
        with patch("app.services.auth_service.verify_password", return_value=False):
            with pytest.raises(AppError) as exc_info:
                await svc.login(LoginRequest(email="user@example.com", password="Str0ng!Pass"))
        assert exc_info.value.code == "INVALID_CREDENTIALS"

    async def test_login_inactive_user_raises(self, mock_session):
        from app.services.auth_service import AuthService
        from app.schemas.auth import LoginRequest
        from app.utils.errors import AppError

        user = make_user(is_active=False)
        mock_session.scalar.return_value = user

        svc = AuthService(mock_session)
        with patch("app.services.auth_service.verify_password", return_value=True):
            with pytest.raises(AppError) as exc_info:
                await svc.login(LoginRequest(email="user@example.com", password="Str0ng!Pass"))
        assert exc_info.value.code == "USER_INACTIVE"

    async def test_login_user_not_found_raises(self, mock_session):
        from app.services.auth_service import AuthService
        from app.schemas.auth import LoginRequest
        from app.utils.errors import AppError

        mock_session.scalar.return_value = None

        svc = AuthService(mock_session)
        with pytest.raises(AppError) as exc_info:
            await svc.login(LoginRequest(email="ghost@example.com", password="Str0ng!Pass"))
        assert exc_info.value.code == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
class TestAuthServiceRefresh:
    async def test_refresh_valid_token(self, mock_session):
        from app.services.auth_service import AuthService
        from app.services.token_service import TokenService

        ts = TokenService()
        user_id = uuid.uuid4()
        refresh_token, expires_at = ts.create_refresh_token(str(user_id))

        token_record = make_refresh_token(
            user_id=user_id,
            token_hash=ts.hash_token(refresh_token),
            expires_at=expires_at,
        )
        token_record.revoked_at = None
        token_record.tenant_id = None

        mock_session.scalar.return_value = token_record
        mock_session.flush = AsyncMock()

        svc = AuthService(mock_session)
        svc.token_service.issue_token_pair = AsyncMock(
            return_value=MagicMock(access_token="new_acc", refresh_token="new_ref", token_type="Bearer", expires_in=900)
        )

        result = await svc.refresh(refresh_token)
        assert result.access_token == "new_acc"

    async def test_refresh_invalid_token_raises(self, mock_session):
        from app.services.auth_service import AuthService
        from app.utils.errors import AppError

        mock_session.scalar.return_value = None

        svc = AuthService(mock_session)
        with pytest.raises(AppError):
            await svc.refresh("invalid.token.here")
