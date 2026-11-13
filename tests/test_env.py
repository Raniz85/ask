from ask.env import Env, merge, profile_script


def test_merge_combines_variables_with_later_ones_winning() -> None:
    # given two environments setting the same variable and one variable each
    lower = {"EDITOR": "vi", "PAGER": "less"}
    higher = {"EDITOR": "nvim", "LANG": "C.UTF-8"}

    # when merging them
    merged = merge([lower, higher])

    # then every variable is kept, the later environment winning
    assert merged == {"EDITOR": "nvim", "PAGER": "less", "LANG": "C.UTF-8"}


def test_merge_removes_variables_set_to_false_from_earlier_environments() -> None:
    # given an environment setting two variables, and a later one removing one
    # of them and a variable no environment sets
    lower = {"EDITOR": "vi", "PAGER": "less"}
    higher: Env = {"EDITOR": False, "LANG": False}

    # when merging them
    merged = merge([lower, higher])

    # then the removed variable is gone, and removing the unset one has no
    # effect
    assert merged == {"PAGER": "less"}


def test_merge_sets_a_removed_variable_again_from_a_later_environment() -> None:
    # given a variable that is set, removed and set again
    envs: list[Env] = [{"EDITOR": "vi"}, {"EDITOR": False}, {"EDITOR": "nvim"}]

    # when merging them
    merged = merge(envs)

    # then the last value is kept
    assert merged == {"EDITOR": "nvim"}


def test_profile_script_exports_every_variable_quoted_for_the_shell() -> None:
    # given variables, one with characters the shell would interpret
    env = {"EDITOR": "nvim", "GREETING": "hello $USER, it's me"}

    # when rendering the profile script
    script = profile_script(env)

    # then each variable is exported with its value quoted
    assert script == (
        "export EDITOR=nvim\nexport GREETING='hello $USER, it'\"'\"'s me'\n"
    )


def test_profile_script_is_empty_without_variables() -> None:
    # given no variables
    # when rendering the profile script
    script = profile_script({})

    # then it is empty
    assert script == ""
