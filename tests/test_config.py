import pytest
from app import create_app


def test_production_requires_random_secret(monkeypatch):
    monkeypatch.setenv('APP_ENV','production')
    monkeypatch.delenv('SECRET_KEY',raising=False)
    with pytest.raises(RuntimeError,match='SECRET_KEY'):
        create_app()


def test_production_cookies_and_headers(monkeypatch,tmp_path):
    monkeypatch.setenv('APP_ENV','production')
    monkeypatch.setenv('SECRET_KEY','configuration-test-secret-of-sufficient-length')
    application=create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':'sqlite://','UPLOAD_DIR':str(tmp_path)})
    assert application.config['SESSION_COOKIE_SECURE']
    assert application.config['SESSION_COOKIE_HTTPONLY']
    response=application.test_client().get('/login')
    assert response.headers['X-Content-Type-Options']=='nosniff'
    assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
    assert response.headers['Cache-Control']=='no-store'
