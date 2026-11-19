from pathlib import Path

from ask.tool_manager import Mise, config_digest, known_names, resolve
from ask.user import ResolvedUser


def _touch(root: Path, *relative_paths: str) -> None:
    for relative_path in relative_paths:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")


def test_mise_is_installed_from_its_package() -> None:
    # given the mise tool manager
    mise = Mise()

    # when resolving its packages for arch
    packages = mise.packages_for("arch")

    # then the mise package is installed
    assert packages == ["mise"]


def test_mise_installs_git_on_debian() -> None:
    # given the mise tool manager
    mise = Mise()

    # when resolving its packages for debian, which has no mise package
    packages = mise.packages_for("debian")

    # then git (for git-based tools) is installed; the mise apt repository is
    # added by the provisioner itself
    assert packages == ["git"]


def test_mise_finds_a_mise_toml_in_the_project(tmp_path: Path) -> None:
    # given a project with a mise.toml
    _touch(tmp_path, "mise.toml")

    # when looking for mise config files
    config_files = Mise().config_files(tmp_path)

    # then the mise.toml is found
    assert config_files == [Path("mise.toml")]


def test_mise_finds_nothing_in_a_project_without_mise_config(tmp_path: Path) -> None:
    # given a project with other config files, including asdf's .tool-versions
    _touch(tmp_path, "ask.toml", "pyproject.toml", ".tool-versions")

    # when looking for mise config files
    config_files = Mise().config_files(tmp_path)

    # then nothing is found
    assert config_files == []


def test_mise_finds_every_kind_of_mise_config_file(tmp_path: Path) -> None:
    # given a project with mise config files in each supported location
    _touch(
        tmp_path,
        "mise.toml",
        "mise.local.toml",
        "mise.production.toml",
        ".mise.toml",
        ".mise.local.toml",
        "mise/config.toml",
        "mise/conf.d/node.toml",
        "mise/conf.d/erlang/mise.toml",
        ".mise/config.toml",
        ".mise/conf.d/node.toml",
        ".config/mise.toml",
        ".config/mise.local.toml",
        ".config/mise/mise.toml",
        ".config/mise/config.toml",
        ".config/mise/config.local.toml",
        ".config/mise/conf.d/node.toml",
        ".config/mise/conf.d/erlang/mise.toml",
    )

    # when looking for mise config files
    config_files = Mise().config_files(tmp_path)

    # then all of them are found, in a stable order
    assert config_files == sorted(
        [
            Path("mise.toml"),
            Path("mise.local.toml"),
            Path("mise.production.toml"),
            Path(".mise.toml"),
            Path(".mise.local.toml"),
            Path("mise/config.toml"),
            Path("mise/conf.d/node.toml"),
            Path("mise/conf.d/erlang/mise.toml"),
            Path(".mise/config.toml"),
            Path(".mise/conf.d/node.toml"),
            Path(".config/mise.toml"),
            Path(".config/mise.local.toml"),
            Path(".config/mise/mise.toml"),
            Path(".config/mise/config.toml"),
            Path(".config/mise/config.local.toml"),
            Path(".config/mise/conf.d/node.toml"),
            Path(".config/mise/conf.d/erlang/mise.toml"),
        ]
    )


def test_known_names_lists_every_tool_manager() -> None:
    # given the registry of supported tool managers
    # when listing the known tool manager names
    names = known_names()

    # then every supported tool manager is listed, sorted by name
    assert names == ["mise"]


def test_resolve_returns_the_named_tool_manager() -> None:
    # given the name of a supported tool manager
    # when resolving it
    tool_manager = resolve("mise")

    # then the matching tool manager is returned
    assert tool_manager == Mise()


def test_config_digest_is_the_same_for_unchanged_config_files(tmp_path: Path) -> None:
    # given two projects with identical mise config files
    first, second = tmp_path / "first", tmp_path / "second"
    for project_dir in (first, second):
        _touch(project_dir, "mise.toml", ".config/mise/conf.d/node.toml")
        (project_dir / "mise.toml").write_text('[tools]\nerlang = "29.1.1"\n')
    config_files = [Path("mise.toml"), Path(".config/mise/conf.d/node.toml")]

    # when computing the digest of each project's config files
    digests = {config_digest(first, config_files), config_digest(second, config_files)}

    # then the digests are the same
    assert len(digests) == 1


def test_config_digest_changes_when_a_config_file_changes(tmp_path: Path) -> None:
    # given a project with a mise.toml
    (tmp_path / "mise.toml").write_text('[tools]\nerlang = "29.1.1"\n')
    before = config_digest(tmp_path, [Path("mise.toml")])

    # when the mise.toml changes
    (tmp_path / "mise.toml").write_text('[tools]\nerlang = "29.2.0"\n')
    after = config_digest(tmp_path, [Path("mise.toml")])

    # then the digest changes
    assert before != after


def test_config_digest_changes_when_a_config_file_moves(tmp_path: Path) -> None:
    # given a project with identical content in two mise config locations
    _touch(tmp_path, "mise.toml", "mise.local.toml")

    # when computing the digest of each location on its own
    digests = {
        config_digest(tmp_path, [Path("mise.toml")]),
        config_digest(tmp_path, [Path("mise.local.toml")]),
    }

    # then the digests differ, since mise treats those files differently
    assert len(digests) == 2


def test_mise_puts_its_shims_on_the_users_path() -> None:
    # given a user
    user = ResolvedUser(
        name="raniz",
        uid=1000,
        shell="zsh",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )

    # when resolving the directories mise needs on that user's PATH
    path_entries = Mise().path_entries(user)

    # then it is mise's shims directory in the user's home
    assert path_entries == [Path("/home/raniz/.local/share/mise/shims")]
