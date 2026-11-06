"""Fresh-install setup is local, atomic, secret-safe and Windows-friendly."""

import os
from types import SimpleNamespace

import pytest
from dotenv import dotenv_values

from product_assistant.config import Settings
from scripts import configure


def fake_key():
    return "sk-or-v1-" + "0" * 64


def test_cloud_setup_writes_complete_profile_without_echo(tmp_path, capsys):
    path = configure.save_configuration(tmp_path, ask_key=lambda _: fake_key())
    values = dotenv_values(path, encoding="utf-8-sig")
    assert values["APP_MODE"] == "llm"
    assert values["LLM_API_KEY"] == fake_key()
    assert all(values[name] == value for name, value in configure.PRESET.items())
    assert fake_key() not in capsys.readouterr().out
    assert not list(tmp_path.glob(".env.configure-*"))
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("entered", ["", "qwen_new", "sk-or-v1-" + "0 " * 40])
def test_invalid_key_never_overwrites_config(tmp_path, entered):
    path = tmp_path / ".env"
    path.write_text("APP_MODE=demo\nCUSTOM=value\n", encoding="utf-8-sig")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        configure.save_configuration(tmp_path, ask_key=lambda _: entered)
    assert path.read_bytes() == before


def test_existing_key_duplicates_comments_and_unrelated_values_are_preserved(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "# My note\nCUSTOM=keep\nLLM_API_KEY=\nLLM_API_KEY=\n", encoding="utf-8-sig"
    )
    configure.save_configuration(tmp_path, ask_key=lambda _: fake_key())
    values = dotenv_values(path)
    assert values["CUSTOM"] == "keep" and values["LLM_API_KEY"] == fake_key()
    assert "# My note" in path.read_text()
    assert path.read_text().count("LLM_API_KEY=" + fake_key()) == 2
    configure.save_configuration(tmp_path, ask_key=lambda _: "")
    assert dotenv_values(path)["LLM_API_KEY"] == fake_key()


def test_demo_setup_never_asks_key_or_erases_existing_key(tmp_path):
    path = tmp_path / ".env"
    path.write_text("LLM_API_KEY=" + fake_key() + "\n", encoding="utf-8")
    configure.save_configuration(
        tmp_path, demo=True, ask_key=lambda _: pytest.fail("No key prompt in demo")
    )
    assert dotenv_values(path)["APP_MODE"] == "demo"
    assert dotenv_values(path)["LLM_API_KEY"] == fake_key()


def test_setup_requires_hidden_interactive_input(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(configure, "ROOT", tmp_path)
    monkeypatch.setattr(configure.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    assert configure.main([]) == 2
    assert not (tmp_path / ".env").exists()
    assert "обычном окне терминала" in capsys.readouterr().err


def test_cancelled_setup_does_not_create_a_file(monkeypatch, tmp_path):
    monkeypatch.setattr(configure, "ROOT", tmp_path)
    monkeypatch.setattr(configure.sys, "stdin", SimpleNamespace(isatty=lambda: True))

    def interrupted(_):
        raise KeyboardInterrupt()

    monkeypatch.setattr(configure, "getpass", interrupted)
    assert configure.main([]) == 1
    assert not (tmp_path / ".env").exists()


def test_demo_command_works_without_tty(monkeypatch, tmp_path):
    monkeypatch.setattr(configure, "ROOT", tmp_path)
    monkeypatch.setattr(configure.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    assert configure.main(["--demo"]) == 0
    assert dotenv_values(tmp_path / ".env")["APP_MODE"] == "demo"


def test_empty_inherited_windows_key_does_not_shadow_saved_env(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(
        "APP_MODE=llm\nLLM_PROVIDER=openai_compatible\nLLM_MODEL=TEST-FIXTURE\nLLM_BASE_URL=https://openrouter.ai/api/v1\nLLM_API_KEY="
        + fake_key()
        + "\n",
        encoding="utf-8-sig",
    )
    monkeypatch.setenv("LLM_API_KEY", "   ")
    settings = Settings.from_env()
    assert settings.api_key == fake_key() and settings.can_generate


def test_nonempty_environment_key_keeps_priority(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("LLM_API_KEY=" + fake_key() + "\n", encoding="utf-8")
    monkeypatch.setenv("LLM_API_KEY", "ENVIRONMENT-TEST-KEY")
    assert Settings.from_env().api_key == "ENVIRONMENT-TEST-KEY"


def test_default_port_and_plain_windows_logs(monkeypatch):
    import run

    calls = []
    monkeypatch.setattr(
        run.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs))
    )
    assert run.main([]) == 0
    assert calls[0][1]["port"] == 8010 and calls[0][1]["use_colors"] is False


def test_demo_does_not_copy_environment_only_secret_to_disk(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_API_KEY", fake_key())
    configure.save_configuration(tmp_path, demo=True)
    assert dotenv_values(tmp_path / ".env")["LLM_API_KEY"] == ""


def test_setup_warns_about_different_nonempty_environment_key(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(configure, "ROOT", tmp_path)
    monkeypatch.setattr(configure.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setenv("LLM_API_KEY", "EXISTING-ENV-TEST-KEY")
    monkeypatch.setattr(configure, "getpass", lambda _: fake_key())
    assert configure.main([]) == 0
    output = capsys.readouterr().out
    assert "имеет приоритет" in output
    assert fake_key() not in output and "EXISTING-ENV-TEST-KEY" not in output
