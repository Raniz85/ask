import shlex
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from ask.errors import AskError
from ask.setup import (
    SetupStep,
    _command_succeeds,
    _host_codename,
    _host_distribution,
    _sources_file_matches,
    _zabbly_sources_line,
    example_config_path,
    incus_install_steps,
    incus_steps,
    run_setup,
    run_step,
)


def _step(command: list[str], done: bool = False) -> SetupStep:
    return SetupStep(
        description="do a thing",
        command=command,
        done=lambda: done,
    )


def test_run_step_shows_full_command_and_asks_before_running(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given a step whose command needs sudo and has not been done yet
    step = _step(["sudo", "usermod", "-v", "100000-1099999", "raniz"])

    # when running it with a confirmation that accepts
    with patch("subprocess.run") as run:
        ran = run_step(step, confirm=lambda prompt: True)

    # then the full command line was shown and asked about before running
    out = capsys.readouterr().out
    assert shlex.join(step.command) in out
    assert "sudo usermod -v 100000-1099999 raniz" in out
    run.assert_called_once_with(
        ["sudo", "usermod", "-v", "100000-1099999", "raniz"], check=True
    )
    assert ran is True


def test_run_step_skips_when_the_user_declines(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given a step that has not been done yet
    step = _step(["sudo", "incus", "project", "create", "user-1000"])

    # when the user answers no
    with patch("subprocess.run") as run:
        ran = run_step(step, confirm=lambda prompt: False)

    # then the command was shown but never executed
    assert shlex.join(step.command) in capsys.readouterr().out
    run.assert_not_called()
    assert ran is False


def test_run_step_skips_steps_that_are_already_done(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given a step that reports itself as already done
    step = _step(["sudo", "incus", "project", "create", "user-1000"], done=True)

    # when running it
    with patch("subprocess.run") as run:
        ran = run_step(step, confirm=lambda prompt: pytest.fail("should not ask"))

    # then it neither asks nor runs anything
    run.assert_not_called()
    assert ran is False


def test_run_step_reports_failing_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given a step whose command fails
    step = _step(["sudo", "false"])
    failure = subprocess.CalledProcessError(1, step.command, stderr="nope")

    # when running it
    with (
        patch("subprocess.run", side_effect=failure),
        pytest.raises(AskError, match="sudo false"),
    ):
        run_step(step, confirm=lambda prompt: True)


def test_run_step_reports_missing_commands() -> None:
    # given a step whose command is not installed
    step = _step(["sudo", "incus", "project", "create", "user-1000"])
    missing = FileNotFoundError(2, "No such file or directory", "sudo")

    # when running it
    with (
        patch("subprocess.run", side_effect=missing),
        pytest.raises(AskError, match="sudo.*not found"),
    ):
        run_step(step, confirm=lambda prompt: True)


def test_incus_steps_cover_user_project_and_subuid_subgid() -> None:
    # when building the incus setup steps for a user with uid 1000
    steps = incus_steps("raniz", 1000)

    # then the user project is created with sudo, the subuid/subgid steps
    # target the user, and there is no admin-group step
    commands = [step.command for step in steps]
    assert ["sudo", "incus", "project", "create", "user-1000"] in commands
    assert ["incus", "config", "set", "default.project", "user-1000"] in commands
    assert ["sudo", "usermod", "-v", "100000-1099999", "raniz"] in commands
    assert ["sudo", "usermod", "-w", "100000-1099999", "raniz"] in commands
    assert not any("incus-admin" in shlex.join(command) for command in commands)


def test_run_setup_creates_example_config_and_runs_all_steps(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # given a fresh config directory and all steps pending
    config_dir = tmp_path / "ask"
    steps = [_step(["sudo", "incus", "project", "create", "user-1000"])]

    # when running the full setup, accepting every prompt
    with (
        patch("subprocess.run") as run,
        patch("ask.setup.incus_install_steps", return_value=[]),
        patch("ask.setup.incus_steps", return_value=steps),
    ):
        run_setup(
            config_dir=config_dir,
            username="raniz",
            uid=1000,
            confirm=lambda prompt: True,
        )

    # then the example configuration was created and every step ran
    example = example_config_path(config_dir)
    assert example.is_file()
    assert "distribution" in example.read_text()
    out = capsys.readouterr().out
    assert str(example) in out
    run.assert_called_once_with(
        ["sudo", "incus", "project", "create", "user-1000"], check=True
    )


def test_run_setup_does_not_overwrite_an_existing_example_config(
    tmp_path: Path,
) -> None:
    # given a config directory that already has an example configuration
    config_dir = tmp_path / "ask"
    example = example_config_path(config_dir)
    example.parent.mkdir(parents=True)
    example.write_text("# my own configuration\n")

    # when running the setup
    with (
        patch("ask.setup.incus_install_steps", return_value=[]),
        patch("ask.setup.incus_steps", return_value=[]),
    ):
        run_setup(
            config_dir=config_dir,
            username="raniz",
            uid=1000,
            confirm=lambda prompt: True,
        )

    # then the existing file is left untouched
    assert example.read_text() == "# my own configuration\n"


def test_run_setup_prompts_for_the_config_file_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # given a fresh config directory
    config_dir = tmp_path / "ask"
    prompts: list[str] = []

    def confirm(prompt: str) -> bool:
        prompts.append(prompt)
        return False

    # when running the setup but declining everything
    with (
        patch("ask.setup.incus_install_steps", return_value=[]),
        patch("ask.setup.incus_steps", return_value=[_step(["incus", "list"])]),
    ):
        run_setup(config_dir=config_dir, username="raniz", uid=1000, confirm=confirm)

    # then both the config file and the step were offered, and nothing was created
    assert len(prompts) == 2
    assert not example_config_path(config_dir).exists()


def test_example_config_path_lives_under_the_ask_config_dir(tmp_path: Path) -> None:
    assert example_config_path(tmp_path / "ask") == (
        tmp_path / "ask" / "flavors" / "default.toml"
    )


def test_cli_setup_runs_setup_for_the_calling_user(tmp_path: Path) -> None:
    # given the setup command
    from ask import cli

    # when invoked
    with (
        patch("ask.cli.setup_ops.run_setup") as run,
        patch("ask.cli.setup_ops.config_dir", return_value=tmp_path / "ask"),
        patch("ask.cli.pwd.getpwuid") as getpwuid,
    ):
        getpwuid.return_value.pw_name = "raniz"
        getpwuid.return_value.pw_uid = 1000
        cli.setup()

    # then it runs the setup in the ask config dir as the calling user
    run.assert_called_once()
    base, username, uid, confirm = run.call_args.args
    assert base == tmp_path / "ask"
    assert username == "raniz"
    assert uid == 1000
    assert callable(confirm)


def test_setup_is_a_registered_command() -> None:
    from ask import app

    assert "setup" in app.resolved_commands()


def _completed(returncode: int = 0, stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


def _patch_subid_files(tmp_path: Path) -> tuple[Path, Path]:
    subuid_file = tmp_path / "subuid"
    subgid_file = tmp_path / "subgid"
    return subuid_file, subgid_file


def test_incus_step_checks_detect_existing_state(tmp_path: Path) -> None:
    # given the incus steps for a user with uid 1000
    steps = incus_steps("raniz", 1000)
    project, default, subuid, subgid = steps
    subuid_file, subgid_file = _patch_subid_files(tmp_path)

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        if command[:3] == ["incus", "project", "show"]:
            return _completed(0)
        if command[:3] == ["incus", "config", "get"]:
            return _completed(0, stdout="user-1000\n")
        raise AssertionError(f"unexpected command: {command}")

    # when all checks run against an already-configured system
    with (
        patch("ask.setup.subprocess.run", side_effect=fake_run),
        patch("ask.setup.Path") as path_cls,
    ):
        path_cls.side_effect = lambda p: (
            subuid_file if p == "/etc/subuid" else subgid_file
        )
        subuid_file.write_text("raniz:200000:1000000\n")
        subgid_file.write_text("raniz:200000:1000000\n")
        results = [step.done() for step in steps]

    # then every step reports itself as done
    assert results == [True, True, True, True]
    assert [step.description for step in steps] == [
        project.description,
        default.description,
        subuid.description,
        subgid.description,
    ]


def test_incus_step_checks_detect_missing_state(tmp_path: Path) -> None:
    # given the incus steps for a user on an unconfigured system
    steps = incus_steps("raniz", 1000)
    subuid_file, subgid_file = _patch_subid_files(tmp_path)
    subuid_file.write_text("")
    subgid_file.write_text("")

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        return _completed(1)

    # when all checks run
    with (
        patch("ask.setup.subprocess.run", side_effect=fake_run),
        patch("ask.setup.Path") as path_cls,
    ):
        path_cls.side_effect = lambda p: (
            subuid_file if p == "/etc/subuid" else subgid_file
        )
        results = [step.done() for step in steps]

    # then every step reports itself as pending
    assert results == [False, False, False, False]


def test_subid_check_accepts_any_start_as_long_as_the_span_is_large_enough(
    tmp_path: Path,
) -> None:
    from ask.setup import _has_sufficient_subid_range

    subuid = tmp_path / "subuid"
    subuid.write_text("raniz:100000:1000000\n")
    assert _has_sufficient_subid_range(subuid, "raniz") is True
    subuid.write_text("raniz:200000:1000000\n")
    assert _has_sufficient_subid_range(subuid, "raniz") is True
    subuid.write_text("raniz:100000:2000000\n")
    assert _has_sufficient_subid_range(subuid, "raniz") is True


def test_subid_check_rejects_too_small_spans(tmp_path: Path) -> None:
    from ask.setup import _has_sufficient_subid_range

    subuid = tmp_path / "subuid"
    subuid.write_text("raniz:100000:65536\n")  # the usual distro default
    assert _has_sufficient_subid_range(subuid, "raniz") is False
    subuid.write_text("raniz:100000:999999\n")
    assert _has_sufficient_subid_range(subuid, "raniz") is False


def test_subid_check_rejects_malformed_or_foreign_entries(tmp_path: Path) -> None:
    from ask.setup import _has_sufficient_subid_range

    subuid = tmp_path / "subuid"
    subuid.write_text("raniz:100000\n")
    assert _has_sufficient_subid_range(subuid, "raniz") is False
    subuid.write_text("raniz:100000:lots\n")
    assert _has_sufficient_subid_range(subuid, "raniz") is False
    subuid.write_text("raniz2:100000:1000000\n")
    assert _has_sufficient_subid_range(subuid, "raniz") is False


def test_subid_check_tolerates_a_missing_file(tmp_path: Path) -> None:
    from ask.setup import _has_sufficient_subid_range

    assert _has_sufficient_subid_range(tmp_path / "does-not-exist", "raniz") is False


def test_config_dir_honours_xdg_config_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ask.setup import config_dir

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_dir() == tmp_path / "ask"


def test_incus_install_steps_for_arch_install_and_init_via_pacman() -> None:
    # when building the incus installation steps for Arch Linux
    steps = incus_install_steps("arch")

    # then incus is installed with pacman and initialised with incus admin init
    commands = [step.command for step in steps]
    assert ["sudo", "pacman", "-S", "--needed", "--noconfirm", "incus"] in commands
    assert ["sudo", "incus", "admin", "init"] in commands


def test_incus_install_steps_are_empty_for_unsupported_distributions() -> None:
    # when building the installation steps for a distribution ask does not
    # support yet
    # then there are no steps
    assert incus_install_steps("fedora") == []
    assert incus_install_steps("") == []


def test_incus_install_steps_for_debian_use_the_zabbly_repo_and_apt() -> None:
    # when building the incus installation steps for a Debian trixie host
    with patch("ask.setup._host_codename", return_value="trixie"):
        steps = incus_install_steps("debian")

    # then the zabbly signing key and repository are added for the host
    # codename, apt installs incus, and incus is initialised
    commands = [shlex.join(step.command) for step in steps]
    assert any(
        "https://pkgs.zabbly.com/key.asc" in command
        and "/etc/apt/keyrings/zabbly.asc" in command
        for command in commands
    )
    assert any(
        "zabbly-incus-stable.list" in command
        and "https://pkgs.zabbly.com/incus/stable trixie main" in command
        for command in commands
    )
    assert ["sudo", "apt-get", "update"] in [step.command for step in steps]
    assert ["sudo", "apt-get", "install", "-y", "incus"] in [
        step.command for step in steps
    ]
    assert ["sudo", "incus", "admin", "init"] in [step.command for step in steps]

    # and the steps run in dependency order: key, repo, update, install, init
    order = [
        next(i for i, c in enumerate(commands) if "key.asc" in c),
        next(i for i, c in enumerate(commands) if "zabbly-incus-stable.list" in c),
        next(i for i, c in enumerate(commands) if c == "sudo apt-get update"),
        next(i for i, c in enumerate(commands) if c == "sudo apt-get install -y incus"),
        next(i for i, c in enumerate(commands) if c == "sudo incus admin init"),
    ]
    assert order == sorted(order)


def test_incus_install_steps_for_debian_without_codename_are_empty() -> None:
    # given a Debian host whose os-release has no VERSION_CODENAME
    with patch("ask.setup._host_codename", return_value=""):
        # when building the installation steps
        # then there are none, rather than a broken repository line
        assert incus_install_steps("debian") == []


def test_debian_install_step_done_checks(tmp_path: Path) -> None:
    # given the debian installation steps for a bookworm host
    with patch("ask.setup._host_codename", return_value="bookworm"):
        key, repo, update, install, init = incus_install_steps("debian")
    key_path = tmp_path / "zabbly.asc"
    sources_path = tmp_path / "zabbly-incus-stable.list"
    sources_line = _zabbly_sources_line("bookworm")

    with (
        patch("ask.setup.ZABBLY_KEY_PATH", key_path),
        patch("ask.setup.ZABBLY_SOURCES_PATH", sources_path),
        patch("ask.setup.shutil.which", return_value=None),
        patch("ask.setup.subprocess.run") as run,
    ):
        run.return_value = _completed(1)

        # when nothing is set up yet, every step is pending
        assert [
            key.done(),
            repo.done(),
            update.done(),
            install.done(),
            init.done(),
        ] == [
            False,
            False,
            False,
            False,
            False,
        ]

        # when the key and repository are in place and incus is installed and
        # initialised, only the apt update step remains pending
        key_path.write_text("key")
        sources_path.write_text(sources_line + "\n")
        with (
            patch("ask.setup.shutil.which", return_value="/usr/bin/incus"),
        ):
            run.return_value = _completed(0)
            assert [
                key.done(),
                repo.done(),
                update.done(),
                install.done(),
                init.done(),
            ] == [True, True, False, True, True]


def test_zabbly_sources_line_targets_the_host_codename() -> None:
    assert _zabbly_sources_line("trixie") == (
        "deb [signed-by=/etc/apt/keyrings/zabbly.asc] "
        "https://pkgs.zabbly.com/incus/stable trixie main"
    )


def test_sources_file_match_requires_the_exact_line(tmp_path: Path) -> None:
    sources = tmp_path / "zabbly-incus-stable.list"
    line = _zabbly_sources_line("trixie")
    assert _sources_file_matches(sources, line) is False
    sources.write_text("# comment\n" + line + "\n")
    assert _sources_file_matches(sources, line) is True
    sources.write_text(line + " extra\n")
    assert _sources_file_matches(sources, line) is False


def test_host_codename_reads_version_codename_from_os_release(tmp_path: Path) -> None:
    # given an os-release file
    os_release = tmp_path / "os-release"
    os_release.write_text(
        'NAME="Debian GNU/Linux"\nID=debian\nVERSION_CODENAME=trixie\n'
    )

    # when detecting the host release codename
    # then VERSION_CODENAME is returned, unquoted
    assert _host_codename(os_release) == "trixie"

    os_release.write_text('NAME="Debian"\nID="debian"\nVERSION_CODENAME="bookworm"\n')
    assert _host_codename(os_release) == "bookworm"

    # and a file without the field, or a missing file, yields an empty string
    os_release.write_text('NAME="Arch Linux"\nID=arch\n')
    assert _host_codename(os_release) == ""
    assert _host_codename(tmp_path / "missing") == ""


def test_install_step_done_check_detects_whether_incus_is_installed() -> None:
    # given the arch installation steps
    install, init = incus_install_steps("arch")

    # when incus is not on PATH
    with patch("ask.setup.shutil.which", return_value=None):
        # then the install step is pending
        assert install.done() is False

    # when incus is on PATH
    with patch("ask.setup.shutil.which", return_value="/usr/bin/incus"):
        # then the install step is done
        assert install.done() is True

    # and the init step is done only when incus list succeeds
    with (
        patch("ask.setup.shutil.which", return_value="/usr/bin/incus"),
        patch("ask.setup.subprocess.run") as run,
    ):
        run.return_value = _completed(1)
        assert init.done() is False
        run.return_value = _completed(0)
        assert init.done() is True
        run.assert_called_with(["incus", "list"], check=False, capture_output=True)


def test_command_succeeds_is_false_when_the_command_is_missing() -> None:
    # given a command that is not installed
    with patch("ask.setup.subprocess.run", side_effect=FileNotFoundError(2, "missing")):
        # when checking whether it succeeds
        # then the check reports False instead of raising
        assert _command_succeeds(["incus", "list"]) is False


def test_host_distribution_reads_the_id_from_os_release(tmp_path: Path) -> None:
    # given an os-release file
    os_release = tmp_path / "os-release"
    os_release.write_text('NAME="Arch Linux"\nID=arch\nID_LIKE=archlinux\n')

    # when detecting the host distribution
    # then the ID is returned, unquoted
    assert _host_distribution(os_release) == "arch"

    os_release.write_text('NAME="Debian"\nID="debian"\n')
    assert _host_distribution(os_release) == "debian"


def test_host_distribution_tolerates_a_missing_os_release(tmp_path: Path) -> None:
    assert _host_distribution(tmp_path / "os-release") == ""


def test_run_setup_runs_install_steps_before_the_incus_steps(
    tmp_path: Path,
) -> None:
    # given a fresh config directory on an Arch host, with one install step
    # and one incus step
    config_dir = tmp_path / "ask"
    install = _step(["sudo", "pacman", "-S", "--needed", "--noconfirm", "incus"])
    incus = _step(["sudo", "incus", "project", "create", "user-1000"])

    # when running the full setup
    with (
        patch("ask.setup._host_distribution", return_value="arch"),
        patch("ask.setup.incus_install_steps", return_value=[install]),
        patch("ask.setup.incus_steps", return_value=[incus]),
        patch("ask.setup.run_step") as run_step_mock,
    ):
        run_setup(
            config_dir=config_dir, username="raniz", uid=1000, confirm=lambda p: True
        )

    # then the install step runs before the incus step
    assert [c.args[0] for c in run_step_mock.call_args_list] == [install, incus]


def test_host_distribution_is_empty_when_os_release_has_no_id(tmp_path: Path) -> None:
    os_release = tmp_path / "os-release"
    os_release.write_text('NAME="Something"\nVERSION_ID="1"\n')
    assert _host_distribution(os_release) == ""
