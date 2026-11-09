"""
Tests for hermes_cli.mcp_config — ``hermes mcp`` subcommands.

These tests mock the MCP server connection layer so they run without
any actual MCP servers or API keys.
"""

import argparse
import json
import os
import types
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """Redirect all config I/O to a temp directory."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(
        "hermes_cli.config.get_hermes_home", lambda: tmp_path
    )
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    monkeypatch.setattr(
        "hermes_cli.config.get_config_path", lambda: config_path
    )
    monkeypatch.setattr(
        "hermes_cli.config.get_env_path", lambda: env_path
    )
    return tmp_path


def _make_args(**kwargs):
    """Build a minimal argparse.Namespace."""
    defaults = {
        "name": "test-server",
        "url": None,
        "command": None,
        "args": None,
        "auth": None,
        "preset": None,
        "env": None,
        "mcp_action": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _seed_config(tmp_path: Path, mcp_servers: dict):
    """Write a config.yaml with the given mcp_servers."""
    import yaml

    config = {"mcp_servers": mcp_servers, "_config_version": 9}
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f)


class FakeTool:
    """Mimics an MCP tool object returned by the SDK."""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description


# ---------------------------------------------------------------------------
# Tests: cmd_mcp_list
# ---------------------------------------------------------------------------

class TestMcpList:
    def test_list_empty_config(self, tmp_path, capsys):
        from hermes_cli.mcp_config import cmd_mcp_list

        cmd_mcp_list()
        out = capsys.readouterr().out
        assert "No MCP servers configured" in out

    def test_list_with_servers(self, tmp_path, capsys):
        _seed_config(tmp_path, {
            "ink": {
                "url": "https://mcp.ml.ink/mcp",
                "enabled": True,
                "tools": {"include": ["create_service", "get_service"]},
            },
            "github": {
                "command": "npx",
                "args": ["@mcp/github"],
                "enabled": False,
            },
        })
        from hermes_cli.mcp_config import cmd_mcp_list

        cmd_mcp_list()
        out = capsys.readouterr().out
        assert "ink" in out
        assert "github" in out
        assert "2 selected" in out  # ink has 2 in include
        assert "disabled" in out  # github is disabled

    def test_list_enabled_default_true(self, tmp_path, capsys):
        """Server without explicit enabled key defaults to enabled."""
        _seed_config(tmp_path, {
            "myserver": {"url": "https://example.com/mcp"},
        })
        from hermes_cli.mcp_config import cmd_mcp_list

        cmd_mcp_list()
        out = capsys.readouterr().out
        assert "myserver" in out
        assert "enabled" in out


# ---------------------------------------------------------------------------
# Tests: cmd_mcp_remove
# ---------------------------------------------------------------------------

class TestMcpRemove:
    def test_remove_existing_server(self, tmp_path, capsys, monkeypatch):
        _seed_config(tmp_path, {
            "myserver": {"url": "https://example.com/mcp"},
        })
        monkeypatch.setattr("builtins.input", lambda _: "y")
        from hermes_cli.mcp_config import cmd_mcp_remove

        cmd_mcp_remove(_make_args(name="myserver"))

        out = capsys.readouterr().out
        assert "Removed" in out

        # Verify config updated
        from hermes_cli.config import load_config

        config = load_config()
        assert "myserver" not in config.get("mcp_servers", {})

    def test_remove_nonexistent(self, tmp_path, capsys):
        _seed_config(tmp_path, {})
        from hermes_cli.mcp_config import cmd_mcp_remove

        cmd_mcp_remove(_make_args(name="ghost"))
        out = capsys.readouterr().out
        assert "not found" in out

    def test_remove_cleans_oauth_tokens(self, tmp_path, capsys, monkeypatch):
        _seed_config(tmp_path, {
            "oauth-srv": {"url": "https://example.com/mcp", "auth": "oauth"},
        })
        monkeypatch.setattr("builtins.input", lambda _: "y")
        # Also patch get_hermes_home in the mcp_config module namespace
        monkeypatch.setattr(
            "hermes_cli.mcp_config.get_hermes_home", lambda: tmp_path
        )

        # Create a fake token file
        token_dir = tmp_path / "mcp-tokens"
        token_dir.mkdir()
        token_file = token_dir / "oauth-srv.json"
        token_file.write_text("{}")

        from hermes_cli.mcp_config import cmd_mcp_remove

        cmd_mcp_remove(_make_args(name="oauth-srv"))
        assert not token_file.exists()


# ---------------------------------------------------------------------------
# Tests: cmd_mcp_add
# ---------------------------------------------------------------------------

class TestMcpAdd:
    def test_add_no_transport(self, capsys):
        """Must specify --url or --command."""
        from hermes_cli.mcp_config import cmd_mcp_add

        cmd_mcp_add(_make_args(name="bad"))
        out = capsys.readouterr().out
        assert "Must specify" in out

    def test_add_http_server_all_tools(self, tmp_path, capsys, monkeypatch):
        """Add an HTTP server, accept all tools."""
        fake_tools = [
            FakeTool("create_service", "Deploy from repo"),
            FakeTool("list_services", "List all services"),
        ]

        def mock_probe(name, config, **kw):
            return [(t.name, t.description) for t in fake_tools]

        monkeypatch.setattr(
            "hermes_cli.mcp_config._probe_single_server", mock_probe
        )
        # No auth, accept all tools
        inputs = iter(["n", ""])  # no auth needed, enable all
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        from hermes_cli.mcp_config import cmd_mcp_add

        cmd_mcp_add(_make_args(name="ink", url="https://mcp.ml.ink/mcp"))
        out = capsys.readouterr().out
        assert "Saved" in out
        assert "2/2 tools" in out

        # Verify config written
        from hermes_cli.config import load_config

        config = load_config()
        assert "ink" in config.get("mcp_servers", {})
        assert config["mcp_servers"]["ink"]["url"] == "https://mcp.ml.ink/mcp"

    def test_add_stdio_server(self, tmp_path, capsys, monkeypatch):
        """Add a stdio server."""
        fake_tools = [FakeTool("search", "Search repos")]

        def mock_probe(name, config, **kw):
            return [(t.name, t.description) for t in fake_tools]

        monkeypatch.setattr(
            "hermes_cli.mcp_config._probe_single_server", mock_probe
        )
        inputs = iter([""])  # accept all tools
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        from hermes_cli.mcp_config import cmd_mcp_add

        cmd_mcp_add(_make_args(
            name="github",
            command="npx",
            args=["@mcp/github"],
        ))
        out = capsys.readouterr().out
        assert "Saved" in out

        from hermes_cli.config import load_config

        config = load_config()
        srv = config["mcp_servers"]["github"]
        assert srv["command"] == "npx"
        assert srv["args"] == ["@mcp/github"]

    def test_add_connection_failure_save_disabled(
        self, tmp_path, capsys, monkeypatch
    ):
        """Failed connection → option to save as disabled."""

        def mock_probe_fail(name, config, **kw):
            raise ConnectionError("Connection refused")

        monkeypatch.setattr(
            "hermes_cli.mcp_config._probe_single_server", mock_probe_fail
        )
        inputs = iter(["n", "y"])  # no auth, yes save disabled
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        from hermes_cli.mcp_config import cmd_mcp_add

        cmd_mcp_add(_make_args(name="broken", url="https://bad.host/mcp"))
        out = capsys.readouterr().out
        assert "disabled" in out

        from hermes_cli.config import load_config

        config = load_config()
        assert config["mcp_servers"]["broken"]["enabled"] is False

    def test_add_stdio_server_with_env(self, tmp_path, capsys, monkeypatch):
        """Stdio servers can persist explicit environment variables."""
        fake_tools = [FakeTool("search", "Search repos")]

        def mock_probe(name, config, **kw):
            assert config["env"] == {
                "MY_API_KEY": "secret123",
                "DEBUG": "true",
            }
            return [(t.name, t.description) for t in fake_tools]

        monkeypatch.setattr(
            "hermes_cli.mcp_config._probe_single_server", mock_probe
        )
        monkeypatch.setattr("builtins.input", lambda _: "")

        from hermes_cli.mcp_config import cmd_mcp_add

        cmd_mcp_add(_make_args(
            name="github",
            command="npx",
            args=["@mcp/github"],
            env=["MY_API_KEY=secret123", "DEBUG=true"],
        ))
        out = capsys.readouterr().out
        assert "Saved" in out

        from hermes_cli.config import load_config

        config = load_config()
        srv = config["mcp_servers"]["github"]
        assert srv["env"] == {
            "MY_API_KEY": "secret123",
            "DEBUG": "true",
        }

    def test_add_stdio_server_rejects_invalid_env_name(self, capsys):
        """Invalid environment variable names are rejected up front."""
        from hermes_cli.mcp_config import cmd_mcp_add

        cmd_mcp_add(_make_args(
            name="github",
            command="npx",
            args=["@mcp/github"],
            env=["BAD-NAME=value"],
        ))
        out = capsys.readouterr().out
        assert "Invalid --env variable name" in out

    def test_add_http_server_rejects_env_flag(self, capsys):
        """The --env flag is only valid for stdio transports."""
        from hermes_cli.mcp_config import cmd_mcp_add

        cmd_mcp_add(_make_args(
            name="ink",
            url="https://mcp.ml.ink/mcp",
            env=["DEBUG=true"],
        ))
        out = capsys.readouterr().out
        assert "only supported for stdio MCP servers" in out

    def test_add_preset_fills_transport(self, tmp_path, capsys, monkeypatch):
        """A preset fills in command/args when no explicit transport given."""
        monkeypatch.setattr(
            "hermes_cli.mcp_config._MCP_PRESETS",
            {"testmcp": {"command": "npx", "args": ["-y", "test-mcp-server"], "display_name": "Test MCP"}},
        )
        fake_tools = [FakeTool("do_thing", "Does a thing")]

        def mock_probe(name, config, **kw):
            assert name == "myserver"
            assert config["command"] == "npx"
            assert config["args"] == ["-y", "test-mcp-server"]
            assert "env" not in config
            return [(t.name, t.description) for t in fake_tools]

        monkeypatch.setattr(
            "hermes_cli.mcp_config._probe_single_server", mock_probe
        )
        monkeypatch.setattr("builtins.input", lambda _: "")

        from hermes_cli.mcp_config import cmd_mcp_add
        from hermes_cli.config import read_raw_config

        cmd_mcp_add(_make_args(name="myserver", preset="testmcp"))
        out = capsys.readouterr().out
        assert "Saved" in out

        config = read_raw_config()
        srv = config["mcp_servers"]["myserver"]
        assert srv["command"] == "npx"
        assert srv["args"] == ["-y", "test-mcp-server"]
        assert "env" not in srv

    def test_preset_does_not_override_explicit_command(self, tmp_path, capsys, monkeypatch):
        """Explicit transports win over presets."""
        monkeypatch.setattr(
            "hermes_cli.mcp_config._MCP_PRESETS",
            {"testmcp": {"command": "npx", "args": ["-y", "test-mcp-server"], "display_name": "Test MCP"}},
        )
        fake_tools = [FakeTool("search", "Search repos")]

        def mock_probe(name, config, **kw):
            assert config["command"] == "uvx"
            assert config["args"] == ["custom-server"]
            assert "env" not in config
            return [(t.name, t.description) for t in fake_tools]

        monkeypatch.setattr(
            "hermes_cli.mcp_config._probe_single_server", mock_probe
        )
        monkeypatch.setattr("builtins.input", lambda _: "")

        from hermes_cli.mcp_config import cmd_mcp_add
        from hermes_cli.config import read_raw_config

        cmd_mcp_add(_make_args(
            name="custom",
            preset="testmcp",
            command="uvx",
            args=["custom-server"],
        ))
        out = capsys.readouterr().out
        assert "Saved" in out

        config = read_raw_config()
        srv = config["mcp_servers"]["custom"]
        assert srv["command"] == "uvx"
        assert srv["args"] == ["custom-server"]
        assert "env" not in srv

    def test_unknown_preset_rejected(self, capsys):
        """An unknown preset name is rejected with a clear error."""
        from hermes_cli.mcp_config import cmd_mcp_add

        cmd_mcp_add(_make_args(name="foo", preset="nonexistent"))
        out = capsys.readouterr().out
        assert "Unknown MCP preset" in out

    def test_add_uses_stdio_command_not_subcommand_dest(
        self, tmp_path, capsys, monkeypatch
    ):
        """The stdio executable is ``--command``, not the ``mcp`` subcommand."""
        seen = {}

        def mock_probe(name, config, **kw):
            seen["config"] = config
            return [("search", "Search repos")]

        monkeypatch.setattr(
            "hermes_cli.mcp_config._probe_single_server", mock_probe
        )
        monkeypatch.setattr("builtins.input", lambda _: "")

        from hermes_cli.mcp_config import cmd_mcp_add
        from hermes_cli.config import load_config

        cmd_mcp_add(_make_args(
            name="github",
            command="mcp",
            stdio_command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
        ))
        out = capsys.readouterr().out
        assert "Saved" in out
        assert seen["config"]["command"] == "npx"
        assert seen["config"]["args"] == ["-y", "@modelcontextprotocol/server-github"]
        srv = load_config()["mcp_servers"]["github"]
        assert srv["command"] == "npx"
        assert "url" not in srv


_ZAPIER_MCP_CONNECT_URL = "https://mcp.zapier.com/api/v1/connect"
_ZAPIER_PRESET_NAMES = ("zapier-github", "zapier-linear", "zapier-airtable")


class TestZapierMcpPresets:
    def test_zapier_presets_share_connect_url_and_oauth(self):
        """GitHub, Linear, and Airtable presets point at Zapier MCP OAuth."""
        from hermes_cli.mcp_config import _MCP_PRESETS, _apply_mcp_preset

        for name in _ZAPIER_PRESET_NAMES:
            preset = _MCP_PRESETS[name]
            assert preset["url"] == _ZAPIER_MCP_CONNECT_URL
            assert preset["auth"] == "oauth"
            assert "headers" not in preset
            assert "env" not in preset

        server_config: Dict[str, Any] = {}
        url, command, cmd_args, applied = _apply_mcp_preset(
            "zapier-linear",
            preset_name="zapier-linear",
            url=None,
            command=None,
            cmd_args=[],
            server_config=server_config,
        )
        assert applied is True
        assert command is None
        assert cmd_args == []
        assert url == _ZAPIER_MCP_CONNECT_URL
        assert server_config["url"] == _ZAPIER_MCP_CONNECT_URL
        assert server_config["auth"] == "oauth"

    def test_apply_preset_copies_allowlisted_keys_only(self, monkeypatch):
        """auth/timeout/connect_timeout/tools copy; headers and env do not."""
        tools = {"include": ["alpha"]}
        monkeypatch.setattr(
            "hermes_cli.mcp_config._MCP_PRESETS",
            {
                "demo": {
                    "url": "https://example.test/mcp",
                    "auth": "oauth",
                    "timeout": 12,
                    "connect_timeout": 3,
                    "tools": tools,
                    "headers": {"Authorization": "Bearer secret"},
                    "env": {"TOKEN": "secret"},
                }
            },
        )
        from hermes_cli.mcp_config import _MCP_PRESETS, _apply_mcp_preset

        server_config: Dict[str, Any] = {}
        _apply_mcp_preset(
            "demo",
            preset_name="demo",
            url=None,
            command=None,
            cmd_args=[],
            server_config=server_config,
        )
        assert server_config["url"] == "https://example.test/mcp"
        assert server_config["auth"] == "oauth"
        assert server_config["timeout"] == 12
        assert server_config["connect_timeout"] == 3
        assert server_config["tools"] == {"include": ["alpha"]}
        assert "headers" not in server_config
        assert "env" not in server_config

        server_config["tools"]["include"].append("beta")
        assert _MCP_PRESETS["demo"]["tools"]["include"] == ["alpha"]

    def test_add_honors_preset_oauth_when_auth_omitted(
        self, tmp_path, capsys, monkeypatch
    ):
        """Omitting --auth must not prompt for a bearer token."""
        seen: Dict[str, Any] = {}

        class _Mgr:
            def get_or_build_provider(self, name, url, oauth_config):
                seen["provider"] = (name, url, oauth_config)
                return object()

        monkeypatch.setattr(
            "tools.mcp_oauth_manager.get_manager", lambda: _Mgr()
        )

        def mock_probe(name, config, **kw):
            seen["probe_config"] = dict(config)
            return [("list_issues", "List issues")]

        monkeypatch.setattr(
            "hermes_cli.mcp_config._probe_single_server", mock_probe
        )
        prompts: List[str] = []

        def fake_input(prompt=""):
            prompts.append(str(prompt))
            return ""

        monkeypatch.setattr("builtins.input", fake_input)

        from hermes_cli.mcp_config import cmd_mcp_add
        from hermes_cli.config import load_config

        cmd_mcp_add(_make_args(name="zapier-linear", preset="zapier-linear"))
        out = capsys.readouterr().out
        assert "Saved" in out

        prompt_text = "\n".join(prompts).lower()
        assert "api key" not in prompt_text
        assert "bearer" not in prompt_text
        assert "require authentication" not in prompt_text

        assert seen["provider"][0] == "zapier-linear"
        assert seen["provider"][1] == _ZAPIER_MCP_CONNECT_URL
        assert seen["probe_config"]["url"] == _ZAPIER_MCP_CONNECT_URL
        assert seen["probe_config"]["auth"] == "oauth"

        srv = load_config()["mcp_servers"]["zapier-linear"]
        assert srv["url"] == _ZAPIER_MCP_CONNECT_URL
        assert srv["auth"] == "oauth"

    def test_cli_mcp_add_preset_does_not_fall_through_to_chat(self, monkeypatch):
        """``--command`` must not clobber the top-level subcommand dest."""
        import sys
        import hermes_cli.main as main_mod
        import hermes_cli.mcp_config as mcp_config

        captured: Dict[str, Any] = {}

        def fake_add(args):
            captured["add"] = args

        def fake_chat(args):
            captured["chat"] = args

        monkeypatch.setattr(mcp_config, "cmd_mcp_add", fake_add)
        monkeypatch.setattr(main_mod, "cmd_chat", fake_chat)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "hermes",
                "mcp",
                "add",
                "zapier-linear",
                "--preset",
                "zapier-linear",
                "--auth",
                "oauth",
            ],
        )

        main_mod.main()

        assert "chat" not in captured
        args = captured["add"]
        assert args.command == "mcp"
        assert args.stdio_command is None
        assert args.name == "zapier-linear"
        assert args.preset == "zapier-linear"
        assert args.auth == "oauth"


# ---------------------------------------------------------------------------
# Tests: cmd_mcp_test
# ---------------------------------------------------------------------------

class TestMcpTest:
    def test_test_not_found(self, tmp_path, capsys):
        _seed_config(tmp_path, {})
        from hermes_cli.mcp_config import cmd_mcp_test

        cmd_mcp_test(_make_args(name="ghost"))
        out = capsys.readouterr().out
        assert "not found" in out

    def test_test_success(self, tmp_path, capsys, monkeypatch):
        _seed_config(tmp_path, {
            "ink": {"url": "https://mcp.ml.ink/mcp"},
        })

        def mock_probe(name, config, **kw):
            return [("create_service", "Deploy"), ("list_services", "List all")]

        monkeypatch.setattr(
            "hermes_cli.mcp_config._probe_single_server", mock_probe
        )
        from hermes_cli.mcp_config import cmd_mcp_test

        cmd_mcp_test(_make_args(name="ink"))
        out = capsys.readouterr().out
        assert "Connected" in out
        assert "Tools discovered: 2" in out


# ---------------------------------------------------------------------------
# Tests: env var interpolation
# ---------------------------------------------------------------------------

class TestEnvVarInterpolation:
    def test_interpolate_simple(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "secret123")
        from tools.mcp_tool import _interpolate_env_vars

        result = _interpolate_env_vars("Bearer ${MY_KEY}")
        assert result == "Bearer secret123"

    def test_interpolate_missing_var(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        from tools.mcp_tool import _interpolate_env_vars

        result = _interpolate_env_vars("Bearer ${MISSING_VAR}")
        assert result == "Bearer ${MISSING_VAR}"

    def test_interpolate_nested_dict(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "abc")
        from tools.mcp_tool import _interpolate_env_vars

        result = _interpolate_env_vars({
            "url": "https://example.com",
            "headers": {"Authorization": "Bearer ${API_KEY}"},
        })
        assert result["headers"]["Authorization"] == "Bearer abc"
        assert result["url"] == "https://example.com"

    def test_interpolate_list(self, monkeypatch):
        monkeypatch.setenv("ARG1", "hello")
        from tools.mcp_tool import _interpolate_env_vars

        result = _interpolate_env_vars(["${ARG1}", "static"])
        assert result == ["hello", "static"]

    def test_interpolate_non_string(self):
        from tools.mcp_tool import _interpolate_env_vars

        assert _interpolate_env_vars(42) == 42
        assert _interpolate_env_vars(True) is True
        assert _interpolate_env_vars(None) is None


# ---------------------------------------------------------------------------
# Tests: config helpers
# ---------------------------------------------------------------------------

class TestConfigHelpers:
    def test_save_and_load_mcp_server(self, tmp_path):
        from hermes_cli.mcp_config import _save_mcp_server, _get_mcp_servers

        _save_mcp_server("mysvr", {"url": "https://example.com/mcp"})
        servers = _get_mcp_servers()
        assert "mysvr" in servers
        assert servers["mysvr"]["url"] == "https://example.com/mcp"

    def test_remove_mcp_server(self, tmp_path):
        from hermes_cli.mcp_config import (
            _save_mcp_server,
            _remove_mcp_server,
            _get_mcp_servers,
        )

        _save_mcp_server("s1", {"command": "test"})
        _save_mcp_server("s2", {"command": "test2"})
        result = _remove_mcp_server("s1")
        assert result is True
        assert "s1" not in _get_mcp_servers()
        assert "s2" in _get_mcp_servers()

    def test_remove_nonexistent(self, tmp_path):
        from hermes_cli.mcp_config import _remove_mcp_server

        assert _remove_mcp_server("ghost") is False

    def test_env_key_for_server(self):
        from hermes_cli.mcp_config import _env_key_for_server

        assert _env_key_for_server("ink") == "MCP_INK_API_KEY"
        assert _env_key_for_server("my-server") == "MCP_MY_SERVER_API_KEY"


# ---------------------------------------------------------------------------
# Tests: dispatcher
# ---------------------------------------------------------------------------

class TestDispatcher:
    def test_no_action_shows_list(self, tmp_path, capsys):
        from hermes_cli.mcp_config import mcp_command

        _seed_config(tmp_path, {})
        mcp_command(_make_args(mcp_action=None))
        out = capsys.readouterr().out
        assert "Commands:" in out or "No MCP servers" in out


# ---------------------------------------------------------------------------
# Tests: Task 7 consolidation — cmd_mcp_remove evicts manager cache,
# cmd_mcp_login forces re-auth
# ---------------------------------------------------------------------------


class TestMcpRemoveEvictsManager:
    def test_remove_evicts_in_memory_provider(self, tmp_path, capsys, monkeypatch):
        """After cmd_mcp_remove, the MCPOAuthManager no longer caches the provider."""
        _seed_config(tmp_path, {
            "oauth-srv": {"url": "https://example.com/mcp", "auth": "oauth"},
        })
        monkeypatch.setattr("builtins.input", lambda _: "y")
        monkeypatch.setattr(
            "hermes_cli.mcp_config.get_hermes_home", lambda: tmp_path
        )
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        from tools.mcp_oauth_manager import get_manager, reset_manager_for_tests
        reset_manager_for_tests()

        mgr = get_manager()
        mgr.get_or_build_provider(
            "oauth-srv", "https://example.com/mcp", None,
        )
        assert "oauth-srv" in mgr._entries

        from hermes_cli.mcp_config import cmd_mcp_remove
        cmd_mcp_remove(_make_args(name="oauth-srv"))

        assert "oauth-srv" not in mgr._entries


class TestMcpLogin:
    def test_login_rejects_unknown_server(self, tmp_path, capsys):
        _seed_config(tmp_path, {})
        from hermes_cli.mcp_config import cmd_mcp_login
        cmd_mcp_login(_make_args(name="ghost"))
        out = capsys.readouterr().out
        assert "not found" in out

    def test_login_rejects_non_oauth_server(self, tmp_path, capsys):
        _seed_config(tmp_path, {
            "srv": {"url": "https://example.com/mcp", "auth": "header"},
        })
        from hermes_cli.mcp_config import cmd_mcp_login
        cmd_mcp_login(_make_args(name="srv"))
        out = capsys.readouterr().out
        assert "not configured for OAuth" in out

    def test_login_rejects_stdio_server(self, tmp_path, capsys):
        _seed_config(tmp_path, {
            "srv": {"command": "npx", "args": ["some-server"]},
        })
        from hermes_cli.mcp_config import cmd_mcp_login
        cmd_mcp_login(_make_args(name="srv"))
        out = capsys.readouterr().out
        assert "no URL" in out or "not an OAuth" in out

