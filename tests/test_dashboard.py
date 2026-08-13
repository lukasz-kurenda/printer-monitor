# -*- coding: utf-8 -*-
"""Testy autoryzacji dashboardu (SEC-K3): login token, sesja, CSRF."""

import os
import sqlite3

os.environ.setdefault('DASH_AUTH_TOKEN', 'test-token-123')

import dashboard  # noqa: E402
import lockfile  # noqa: E402
import pytest  # noqa: E402

TOKEN = 'test-token-123'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(dashboard, 'DB_FILE', str(tmp_path / 'printers.db'))
    monkeypatch.setattr(dashboard, 'PRINTERS_FILE', str(tmp_path / 'printers.csv'))
    monkeypatch.setattr(dashboard, 'CONFIG_FILE', str(tmp_path / 'config.ini'))
    monkeypatch.setattr(dashboard, 'LOCK_FILE', str(tmp_path / 'script.lock'))
    (tmp_path / 'config.ini').write_text('[MONITORING]\ntoner_filter_keywords = toner\n')
    (tmp_path / 'printers.csv').write_text('172.21.0.11\n')
    con = sqlite3.connect(str(tmp_path / 'printers.db'))
    con.execute(
        "CREATE TABLE toner_status ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " ip_address TEXT NOT NULL, model TEXT, device_name TEXT, location TEXT,"
        " toner_desc TEXT NOT NULL, toner_level REAL, last_updated TEXT,"
        " alert_sent_timestamp TEXT, UNIQUE(ip_address, toner_desc))"
    )
    con.execute(
        "CREATE TABLE script_runs ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, run_type TEXT, run_timestamp TEXT)"
    )
    con.commit()
    con.close()
    monkeypatch.setattr(dashboard, 'run_background_script', lambda cmd, log: (True, 'ok'))
    dashboard.app.config['TESTING'] = True
    with dashboard.app.test_client() as test_client:
        yield test_client


def _csrf(client):
    client.get('/login')
    with client.session_transaction() as sess:
        return sess['csrf_token']


def _auth(client, csrf=None):
    with client.session_transaction() as sess:
        sess['authenticated'] = True
        sess['csrf_token'] = csrf or 'csrf123'


def test_index_requires_login(client):
    rv = client.get('/')
    assert rv.status_code == 302
    assert '/login' in rv.headers['Location']


def test_login_page_ok(client):
    rv = client.get('/login')
    assert rv.status_code == 200


def test_login_wrong_token(client):
    csrf = _csrf(client)
    rv = client.post('/login', data={'token': 'wrong', 'csrf_token': csrf})
    assert rv.status_code == 401


def test_login_success_and_access(client):
    csrf = _csrf(client)
    rv = client.post('/login', data={'token': TOKEN, 'csrf_token': csrf})
    assert rv.status_code == 302
    rv = client.get('/')
    assert rv.status_code == 200
    assert '172.21.0.11' in rv.get_data(as_text=True)


def test_session_is_permanent_after_login(client):
    csrf = _csrf(client)
    client.post('/login', data={'token': TOKEN, 'csrf_token': csrf})
    with client.session_transaction() as sess:
        assert sess.permanent is True


def test_post_without_csrf_blocked(client):
    _auth(client)
    rv = client.post('/run-check-toner')
    assert rv.status_code == 403


def test_post_with_csrf_ok(client):
    _auth(client, csrf='csrf123')
    rv = client.post('/run-check-toner', headers={'X-CSRF-Token': 'csrf123'})
    assert rv.status_code == 200
    assert rv.get_json()['status'] == 'success'


def test_post_with_wrong_csrf_blocked(client):
    _auth(client, csrf='csrf123')
    rv = client.post('/run-check-toner', headers={'X-CSRF-Token': 'bad'})
    assert rv.status_code == 403


def test_logout_clears_session(client):
    _auth(client, csrf='csrf123')
    rv = client.post('/logout', headers={'X-CSRF-Token': 'csrf123'})
    assert rv.status_code == 302
    assert client.get('/').status_code == 302


def test_run_check_toner_409_when_locked(client):
    _auth(client, csrf='csrf123')
    assert lockfile.acquire(dashboard.LOCK_FILE) is True
    try:
        rv = client.post('/run-check-toner', headers={'X-CSRF-Token': 'csrf123'})
        assert rv.status_code == 409
    finally:
        lockfile.release(dashboard.LOCK_FILE)
